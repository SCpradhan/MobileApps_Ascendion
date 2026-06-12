"""Turn search hits into an impact set grouped by automation layer.

Layers (config.LAYER_RULES): locator (resources/ui_map), page_object
(libs/flows), test (tests/.../Framework), test_data. Hits outside these roots
are kept under "other" so noise (e.g. iOS bell tests) is visible but clearly
out of scope.

Beyond classifying raw search hits, this module does deterministic cross-layer
expansion using the page-object pattern: locator key -> page-object methods
that use it -> tests that call those methods. That guarantees the report covers
all three layers even if the search engine only returned one.
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

import config


@dataclass
class ImpactedFile:
    path: str
    layer: str
    score: float = 0.0
    lines: set = field(default_factory=set)
    symbols: set = field(default_factory=set)
    evidence: list = field(default_factory=list)
    suggested_action: str = ""


def classify(path):
    for layer, prefix in config.LAYER_RULES:
        if path.startswith(prefix):
            return layer
    return "other"


def _defect_keywords(defect):
    words = re.findall(r"[a-z][a-z0-9_]{3,}", (defect.get("title", "") + " "
                       + defect.get("component", "")).lower())
    return set(words)


def _locator_keys_in_defect(defect):
    """Locator keys, across ALL ui_map files for this component, mentioned in
    the defect's narrative fields (title/description/steps). Independent of
    search hits: BM25/lucene rarely matches JSON locator config against prose,
    so this is the deterministic entry point for the locator -> page object ->
    test expansion.

    Only title/description/steps are searched (not stack_trace, which is full
    of file paths like ".../bell_icon.py" whose stem would otherwise
    substring-match the unrelated "bell_icon" locator key). Matches require
    non-identifier characters on both sides so a short key like "sign_in_btn"
    can't match inside a longer one like "notifications_panel_sign_in_btn".
    """
    text = " ".join([defect.get("title", ""), defect.get("description", "")]
                    + defect.get("steps_to_reproduce", []))
    keys = {}
    ui_map_root = config.REPO_ROOT / "resources/ui_map/windows/hpx_rebranding"
    for abs_path in sorted(ui_map_root.glob("*.json")):
        try:
            ui_map = json.loads(abs_path.read_text())
        except ValueError:
            continue
        rel_path = str(abs_path.relative_to(config.REPO_ROOT))
        for key in ui_map:
            if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", text):
                keys.setdefault(rel_path, []).append(key)
    return keys


def _grep(root, needle):
    """(relative_path, line_no, line) for every occurrence of needle under root."""
    hits = []
    for path in sorted((config.REPO_ROOT / root).rglob("*.py")):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            if needle in line:
                hits.append((str(path.relative_to(config.REPO_ROOT)), line_no, line.strip()))
    return hits


def cross_layer_expand(defect, impacted):
    """locator key -> page objects -> tests, via plain string search."""
    keys_by_file = _locator_keys_in_defect(defect)

    page_object_methods = set()
    for rel_path, keys in keys_by_file.items():
        entry = _ensure(impacted, rel_path, "locator")
        entry.symbols.update(keys)
        entry.score += 5  # locator key explicitly named in defect text
        for key in keys:
            entry.evidence.append(f"defect text mentions locator key '{key}'")
            for po_path, line_no, line in _grep("libs/flows/windows/hpx_rebranding", key):
                po_entry = _ensure(impacted, po_path, "page_object")
                po_entry.lines.add(line_no)
                po_entry.evidence.append(f"uses locator key '{key}' at line {line_no}: {line}")
                # remember the enclosing method names for the test-level grep
                method = _enclosing_method(po_path, line_no)
                if method:
                    po_entry.symbols.add(method)
                    page_object_methods.add(method)

    for method in sorted(page_object_methods):
        for test_path, line_no, line in _grep("tests/windows/hpx_rebranding/Framework", method):
            entry = _ensure(impacted, test_path, "test")
            entry.lines.add(line_no)
            entry.symbols.add(method)
            entry.evidence.append(f"calls {method}() at line {line_no}: {line}")

    # literal UI strings from the defect (e.g. old button label) in tests/test_data
    for literal in re.findall(r"'([^']{8,60})'", defect.get("description", "")):
        for root in ("tests/windows/hpx_rebranding/Framework", "resources/test_data/hpx_rebranding"):
            for path, line_no, line in _grep(root, literal):
                entry = _ensure(impacted, path, classify(path))
                entry.lines.add(line_no)
                entry.evidence.append(f"contains literal \"{literal}\" at line {line_no}")
    return impacted


def _ensure(impacted, path, layer):
    if path not in impacted:
        impacted[path] = ImpactedFile(path=path, layer=layer)
    return impacted[path]


def _enclosing_method(rel_path, line_no):
    lines = (config.REPO_ROOT / rel_path).read_text(errors="replace").splitlines()
    for i in range(min(line_no, len(lines)) - 1, -1, -1):
        match = re.match(r"\s*def\s+(\w+)", lines[i])
        if match:
            return match.group(1)
    return None


def _suggest_action(entry, defect):
    if entry.layer == "locator":
        return ("Update locator(s) " + ", ".join(sorted(entry.symbols)) +
                ": adjust xpath/AutomationId to the new UI values; keep old values "
                "as fallback list entries for older builds.")
    if entry.layer == "page_object":
        return ("Likely NO change needed - methods reference locator keys, which "
                "is the point of the indirection. Verify after the locator fix.")
    if entry.layer == "test":
        return ("Re-run after locator fix. Change only if the test asserts the "
                "literal UI text that the defect says changed.")
    if entry.layer == "test_data":
        return "Update stored UI literals if they mirror the changed text."
    return "Out of scope for this defect (non-Windows-hpx_rebranding hit)."


def analyze(defect, chunks, analyse_files=()):
    """chunks: search_client.Chunk list; analyse_files: paths from /api/analyse."""
    impacted = {}
    keywords = _defect_keywords(defect)

    for chunk in chunks:
        entry = _ensure(impacted, chunk.file_path, classify(chunk.file_path))
        if chunk.start_line:
            entry.lines.add(chunk.start_line)
        if chunk.name:
            entry.symbols.add(chunk.name)
        entry.evidence.append(
            f"search hit ({', '.join(q[:40] for q in chunk.queries)}) "
            f"chunk '{chunk.name}' lines {chunk.start_line}-{chunk.end_line}")
        # score: API relevance if present, else query-coverage x chunk density
        entry.score += chunk.score if chunk.score else len(set(chunk.queries))

    for path in analyse_files:
        entry = _ensure(impacted, path, classify(path))
        entry.score += 10  # analyse endpoint named it explicitly
        entry.evidence.append("flagged by /api/analyse")

    impacted = cross_layer_expand(defect, impacted)

    for entry in impacted.values():
        if any(word in entry.path.lower() for word in keywords):
            entry.score += 2
        entry.suggested_action = _suggest_action(entry, defect)

    by_layer = defaultdict(list)
    for entry in impacted.values():
        by_layer[entry.layer].append(entry)
    for layer in by_layer:
        by_layer[layer].sort(key=lambda e: -e.score)
    return dict(by_layer)


if __name__ == "__main__":
    import sys
    import search_client
    defect_path = sys.argv[1] if len(sys.argv) > 1 else str(
        config.DEFECTS_DIR / "DEFECT-1042_bell_signin_rename.json")
    with open(defect_path) as f:
        defect = json.load(f)
    chunks, _, _ = search_client.run_searches(defect)
    for layer, entries in analyze(defect, chunks).items():
        print(f"\n[{layer}]")
        for entry in entries:
            print(f"  {entry.score:6.1f}  {entry.path}  symbols={sorted(entry.symbols)}")
