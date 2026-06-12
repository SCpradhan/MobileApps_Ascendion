"""Client for the code-indexer search/analyse endpoints.

Request shapes come from the Postman collection at the repo root
(Code-Indexing Version4.json). Response schemas are not formally documented,
so parsing is defensive: unknown shapes are logged and skipped, never fatal.
"""
import json
import re
from dataclasses import dataclass, field

import requests

import config

_session = requests.Session()
_session.headers["Content-Type"] = "application/json"


@dataclass
class Chunk:
    file_path: str
    start_line: int = 0
    end_line: int = 0
    name: str = ""
    chunk_type: str = ""
    language: str = ""
    is_test_file: bool = False
    score: float = 0.0
    queries: list = field(default_factory=list)  # provenance: which queries hit this


def _identity():
    return {"owner": config.OWNER, "repo": config.REPO, "branch": config.BRANCH}


def _extract_chunks(payload, query):
    """Normalize whatever /api/search returns into Chunk objects."""
    if isinstance(payload, dict):
        for key in ("results", "chunks", "hits", "matches", "data", "content"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        print(f"  unexpected search response shape: {type(payload).__name__}")
        return []

    chunks = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # results may nest the chunk under "chunk"/"document"/"source"
        inner = item
        for nest in ("chunk", "document", "source"):
            if isinstance(item.get(nest), dict):
                inner = {**item[nest], **{k: v for k, v in item.items() if k != nest}}
                break
        path = inner.get("filePath") or inner.get("file_path") or inner.get("path")
        if not path:
            continue
        chunks.append(Chunk(
            file_path=str(path).replace("\\", "/"),
            start_line=int(inner.get("startLine") or inner.get("start_line") or 0),
            end_line=int(inner.get("endLine") or inner.get("end_line") or 0),
            name=inner.get("name") or "",
            chunk_type=inner.get("chunkType") or inner.get("chunk_type") or "",
            language=inner.get("language") or "",
            is_test_file=bool(inner.get("isTestFile") or inner.get("is_test_file")),
            score=float(inner.get("score") or inner.get("relevance") or 0.0),
            queries=[query],
        ))
    return chunks


def search(query, identity=None):
    body = {
        "source": config.SOURCE,
        "destination": config.DESTINATION,
        "repoPath": config.REPO_PATH,
        "query": query,
        **(identity or _identity()),
    }
    resp = _session.post(f"{config.BASE_URL}/api/search", json=body,
                         timeout=config.SEARCH_TIMEOUT_S)
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError:
        print(f"  non-JSON search response ({len(resp.text)} bytes)")
        return [], resp.text
    return _extract_chunks(payload, query), payload


def search_with_fallback(query):
    """Try the configured identity first, then known alternates if empty."""
    for identity in config.IDENTITY_FALLBACKS:
        chunks, raw = search(query, identity=identity)
        if chunks:
            if identity != config.IDENTITY_FALLBACKS[0]:
                print(f"  (search matched under identity {identity})")
            return chunks, raw, identity
    return [], raw, config.IDENTITY_FALLBACKS[0]


def build_queries(defect):
    """2-3 queries per defect: title, extracted identifiers, assertion message."""
    queries = [defect["title"]]

    text = " ".join([defect.get("description", ""), defect.get("stack_trace", "")])
    identifiers = re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text)          # snake_case
    quoted = re.findall(r"'([^']{3,60})'", defect.get("description", ""))
    seen, ident_terms = set(), []
    for term in identifiers + quoted:
        if term not in seen:
            seen.add(term)
            ident_terms.append(term)
    if ident_terms:
        queries.append(" ".join(ident_terms[:10]))

    trace = defect.get("stack_trace", "")
    assertion = next((line.strip() for line in trace.splitlines()
                      if "AssertionError" in line or "Error" in line), "")
    if assertion:
        queries.append(assertion[:200])
    return queries


def run_searches(defect):
    """Union of chunks across queries, merged per (file, name) with provenance."""
    merged, raw_responses, identity_used = {}, {}, None
    for query in build_queries(defect):
        print(f"Searching: {query[:90]}{'...' if len(query) > 90 else ''}")
        chunks, raw, identity = search_with_fallback(query)
        identity_used = identity_used or identity
        raw_responses[query] = raw
        print(f"  -> {len(chunks)} chunk(s)")
        for chunk in chunks:
            key = (chunk.file_path, chunk.name, chunk.start_line)
            if key in merged:
                merged[key].queries.extend(chunk.queries)
                merged[key].score = max(merged[key].score, chunk.score)
            else:
                merged[key] = chunk
    return list(merged.values()), raw_responses, identity_used


def analyse(defect):
    body = {
        "title": defect["title"],
        "description": defect.get("description", ""),
        "stackTrace": defect.get("stack_trace", ""),
        "priority": defect.get("priority", "P3"),
        "source": config.SOURCE,
        "destination": config.DESTINATION,
        "repoPath": config.REPO_PATH,
    }
    resp = _session.post(f"{config.BASE_URL}/api/analyse", json=body,
                         timeout=config.ANALYSE_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def analyse_suspect_files(analysis):
    """Pull file paths out of an /api/analyse response, wherever they hide."""
    paths = []

    def _walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("filePath", "file", "path", "actualFile") and isinstance(value, str):
                    paths.append(value.replace("\\", "/"))
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str) and "/" in node:
            # plain-text analysis: harvest repo-relative paths mentioned in prose
            for match in re.findall(r"[\w./-]+\.(?:py|json|cfg|xml)", node):
                paths.append(match)

    _walk(analysis)
    seen, unique = set(), []
    for path in paths:
        path = path.lstrip("/")
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def send_feedback(analysis_id, correct, actual_file, notes=""):
    resp = _session.post(
        f"{config.BASE_URL}/api/analyse/{analysis_id}/feedback",
        json={"correct": correct, "actualFile": actual_file, "notes": notes},
        timeout=config.REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def get_accuracy():
    params = {**_identity(), "destination": config.DESTINATION, "repoPath": config.REPO_PATH}
    resp = _session.get(f"{config.BASE_URL}/api/index/accuracy", params=params,
                        timeout=config.REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json() if resp.text else {}


if __name__ == "__main__":
    import sys
    defect_path = sys.argv[1] if len(sys.argv) > 1 else str(
        config.DEFECTS_DIR / "DEFECT-1042_bell_signin_rename.json")
    with open(defect_path) as f:
        defect = json.load(f)
    chunks, _, identity = run_searches(defect)
    print(f"\n{len(chunks)} merged chunks (identity {identity}):")
    for chunk in sorted(chunks, key=lambda c: -c.score)[:20]:
        print(f"  {chunk.score:6.2f}  {chunk.file_path}:{chunk.start_line}-{chunk.end_line}  {chunk.name}")
