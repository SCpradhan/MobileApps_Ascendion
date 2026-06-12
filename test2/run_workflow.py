"""End-to-end QA bug-fix workflow:

defect JSON -> ensure indexer service -> verify/refresh .code_index ->
/api/search (+ optional /api/analyse) -> impact analysis -> markdown report.

Usage:
    python test2/run_workflow.py test2/defects/DEFECT-1042_bell_signin_rename.json \
        [--force-reindex] [--no-analyse] [--keep-service] [--validate]

Exit codes: 0 ok, 2 indexing failed, 3 service unreachable.
"""
import argparse
import json
import sys

import config
import impact_analyzer
import index_manager
import report_generator
import search_client
import service_manager


def _validate(by_layer):
    """Acceptance check: DEFECT-1042 must surface all three automation layers."""
    expected = {
        "locator": "resources/ui_map/windows/hpx_rebranding/bell_icon.json",
        "page_object": "libs/flows/windows/hpx_rebranding/bell_icon.py",
    }
    failures = []
    for layer, path in expected.items():
        if not any(e.path == path for e in by_layer.get(layer, [])):
            failures.append(f"missing {layer} hit: {path}")
    suites = [e.path for e in by_layer.get("test", [])
              if "Framework/bell_notifications/test_suite_" in e.path]
    if not suites:
        failures.append("no bell_notifications test suite identified")
    if failures:
        print("VALIDATION FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return False
    print(f"VALIDATION PASSED: locator + page object + {len(suites)} test suite(s) identified.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("defect", help="path to defect JSON (simulated Jira ticket)")
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--no-analyse", action="store_true",
                        help="skip POST /api/analyse enrichment")
    parser.add_argument("--keep-service", action="store_true",
                        help="leave the jar running even if this run started it")
    parser.add_argument("--validate", action="store_true",
                        help="assert the impact set covers locator+page object+test layers")
    args = parser.parse_args()

    with open(args.defect) as f:
        defect = json.load(f)
    print(f"Defect: {defect.get('key')} - {defect.get('title')}\n")

    try:
        process = service_manager.ensure_service()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 3

    try:
        try:
            index_summary = index_manager.verify_or_refresh(force=args.force_reindex)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            return 2

        chunks, raw_payloads, identity = search_client.run_searches(defect)
        print(f"\nSearch returned {len(chunks)} merged chunk(s).")

        analysis, analyse_files = None, []
        if not args.no_analyse:
            try:
                print("Calling /api/analyse ...")
                analysis = search_client.analyse(defect)
                analyse_files = search_client.analyse_suspect_files(analysis)
                print(f"  analyse flagged {len(analyse_files)} file(s)")
            except Exception as exc:  # enrichment only - never fatal
                print(f"  /api/analyse unavailable, continuing on search alone: {exc}")

        by_layer = impact_analyzer.analyze(defect, chunks, analyse_files)

        report_path = report_generator.write_report(
            defect, by_layer, index_summary,
            queries=search_client.build_queries(defect),
            identity=identity, analysis=analysis, raw_payloads=raw_payloads)

        print(f"\nImpact report: {report_path}")
        ranked = [e for entries in by_layer.values() for e in entries]
        ranked.sort(key=lambda e: -e.score)
        print("Top impacted files:")
        for entry in ranked[:5]:
            print(f"  {entry.score:6.1f}  [{entry.layer}]  {entry.path}")

        if args.validate and not _validate(by_layer):
            return 1
        return 0
    finally:
        if args.keep_service:
            print("Leaving indexer service running (--keep-service).")
        else:
            service_manager.stop_service(process)


if __name__ == "__main__":
    sys.exit(main())
