"""Render the impact analysis into a markdown report under test2/reports/.

This is the only workflow module that writes files, and only into
test2/reports/ (report markdown + raw API response dump).
"""
import json
from datetime import datetime, timezone

import config

LAYER_TITLES = [
    ("locator", "Locators (resources/ui_map) - usually the primary fix"),
    ("page_object", "Page objects (libs/flows)"),
    ("test", "Test suites (tests/.../Framework)"),
    ("test_data", "Test data (resources/test_data)"),
    ("other", "Other hits (out of scope for Windows hpx_rebranding)"),
]


def _fmt_lines(lines):
    return ", ".join(str(n) for n in sorted(lines)[:12]) + (" ..." if len(lines) > 12 else "")


def write_report(defect, by_layer, index_summary, queries, identity, analysis=None,
                 raw_payloads=None):
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    defect_id = defect.get("key", "DEFECT")
    report_path = config.REPORTS_DIR / f"{defect_id}_impact_report.md"
    raw_path = config.REPORTS_DIR / f"{defect_id}_raw.json"

    out = []
    out.append(f"# Impact report: {defect_id}")
    out.append(f"\n_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
               f"by test2/run_workflow.py_\n")
    out.append(f"## Defect\n\n**{defect.get('title', '')}**\n")
    out.append(f"- Priority: {defect.get('priority', '?')} | Component: "
               f"{defect.get('component', '?')} | Platform: {defect.get('platform', '?')}")
    out.append(f"\n{defect.get('description', '')}\n")
    if defect.get("stack_trace"):
        out.append("```\n" + defect["stack_trace"] + "\n```\n")

    out.append("## Index status\n")
    for key, value in index_summary.items():
        out.append(f"- {key}: {value}")
    out.append(f"- search identity used: `{identity}`\n")

    out.append("## Queries issued\n")
    for query in queries:
        out.append(f"- `{query}`")
    out.append("")

    out.append("## Impacted files by layer\n")
    for layer, title in LAYER_TITLES:
        entries = by_layer.get(layer, [])
        if not entries:
            continue
        out.append(f"### {title}\n")
        for entry in entries:
            out.append(f"#### `{entry.path}` (score {entry.score:.1f})")
            if entry.symbols:
                out.append(f"- symbols: {', '.join(sorted(entry.symbols))}")
            if entry.lines:
                out.append(f"- lines: {_fmt_lines(entry.lines)}")
            for evidence in entry.evidence[:8]:
                out.append(f"- evidence: {evidence}")
            if len(entry.evidence) > 8:
                out.append(f"- evidence: ... {len(entry.evidence) - 8} more")
            out.append(f"- **proposed action:** {entry.suggested_action}\n")

    if analysis:
        out.append("## /api/analyse result\n")
        analysis_id = analysis.get("analysisId") or analysis.get("id")
        if analysis_id:
            out.append(f"- analysisId: `{analysis_id}` (use POST "
                       f"/api/analyse/{analysis_id}/feedback after confirming the fix)")
        out.append("- full response captured in the raw JSON dump\n")

    out.append("## Validation checklist\n")
    out.append("- [ ] `curl http://localhost:8080/actuator/health` returns UP")
    out.append("- [ ] Apply the proposed locator/test edits in place")
    out.append("- [ ] `python -m json.tool` on every edited locator JSON")
    out.append("- [ ] `python -m py_compile` on every edited .py file")
    out.append("- [ ] `python -m pytest tests/windows/hpx_rebranding/Framework/"
               "bell_notifications/ --collect-only -q`")
    out.append("- [ ] Full UI run on the remote Windows rig (not possible locally)")
    out.append("- [ ] POST feedback on the analysis with the confirmed file\n")

    report_path.write_text("\n".join(out))
    if raw_payloads is not None:
        raw_path.write_text(json.dumps(
            {"search": raw_payloads, "analyse": analysis}, indent=2, default=str))
    return report_path
