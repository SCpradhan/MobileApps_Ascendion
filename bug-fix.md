# QA Bug-Fix Workflow: Jira Defect → Index Search → Impacted Files → Test Fix

## Context

Joy's ask: when QA logs a Jira defect, we need a repeatable workflow that uses the already-shared code index to find the impacted automation scripts (and app code if needed), propose fixes, and validate them. The repo is `MobileApps` (branch `feature_sushree`); the indexer JAR must be fired and the search API endpoint must be fired as part of the flow.

**User decisions (locked):**
1. `test2/` (currently empty) becomes the **workflow workspace** — tooling, sample defect, reports live there. Actual test fixes happen in-place under `tests/`, `libs/`, `resources/`.
2. Deliverable = technical plan document in the repo **plus** runnable Python scripts demonstrating the full flow end to end.
3. Jira intake = **simulated defect JSON** (no Jira credentials needed).

**Verified repo facts:**
- `code-indexer-2.0.0.jar` (74 MB Spring Boot service, port 8080) at repo root; health at `GET /actuator/health`.
- `Code-Indexing Version4.json` (Postman collection, repo root) defines the API: `POST /api/index`, `GET /api/index/progress?owner=local&repo=MobileApps-main&branch=main`, `POST /api/index/status`, `POST /api/search` (body: source/destination="lucene"/owner/repo/branch/repoPath/query), `POST /api/analyse` (title/description/stackTrace/priority), `POST /api/analyse/{id}/feedback`, `GET /api/index/accuracy`. Request bodies confirmed by parsing the collection.
- `.code_index/` has `index_manifest.json` (lastRun 2026-06-04, repo `NavneetBN47/MobileApps`, **branch `main`**, per-file blobSha map, AST chunking) + 38 shards.
- Existing orchestrator `tests/windows/hpx_rebranding/Framework/bell_notifications/Indexing_API_Trigger_ToolV3_CONFIG.py` has the proven JAR-start/health-wait/trigger/poll pattern, but its config is stale (points at `code-indexer-1.0.0.jar` in a different directory and at a `MobileApps-feature_sushree` sibling checkout). We **reuse the pattern, supersede the config** — do not edit the old file.
- Test stack: pytest + page objects. Verified cross-layer trace for the sample defect: locator key `notifications_panel_sign_in_btn` in `resources/ui_map/windows/hpx_rebranding/bell_icon.json:8` (xpath `//Button[@Name='Sign in / Create account']`) → page object `libs/flows/windows/hpx_rebranding/bell_icon.py:18-24,167-168` → assertions in `test_suite_01:67`, `test_suite_02:34,42`, `test_suite_04:62,85-86` under `Framework/bell_notifications/`.
- Out of scope: `generate_index_4.py` / `indexer.py` (AAVA cloud-platform KB flow) and the 200+ MB `index_outputs/` — the local JAR flow doesn't need them.

## What gets built — `test2/` layout

```
test2/
├── BUGFIX_WORKFLOW.md          # technical plan doc (the handoff deliverable)
├── config.py                   # single source of truth: paths, port, repo identity
├── service_manager.py          # JAR lifecycle + health check
├── index_manager.py            # index verify/refresh + /api/index + progress polling
├── search_client.py            # /api/search, /api/analyse, feedback, accuracy
├── impact_analyzer.py          # chunk → layer mapping, ranking, cross-layer expansion
├── report_generator.py         # markdown impact report
├── run_workflow.py             # CLI orchestrator (end-to-end entry point)
├── defects/
│   └── DEFECT-1042_bell_signin_rename.json
└── reports/                    # generated reports + raw API dumps + service log
```

Plain modules, no package nesting; each has an `if __name__ == "__main__"` smoke block so the demo can run stepwise or end-to-end.

## Module specs

### config.py
- `REPO_ROOT = Path(__file__).resolve().parent.parent` (test2 sits at repo root) — no hardcoded user paths.
- `JAR_PATH = REPO_ROOT / "code-indexer-2.0.0.jar"` (fixes the old tool's 1.0.0 path bug); `INDEX_DIR/MANIFEST_PATH/SHARDS_DIR` under `.code_index/`.
- Service identity matching the manifest and Postman collection: `BASE_URL=http://localhost:8080`, `OWNER="local"`, `REPO="MobileApps-main"`, `BRANCH="main"`, `SOURCE="local"`, `DESTINATION="lucene"`, `REPO_PATH=str(REPO_ROOT)` (fixes the old tool's `MobileApps-feature_sushree` path bug).
- `LAYER_RULES`: ordered prefix → layer pairs: `tests/windows/hpx_rebranding/Framework/` → test, `libs/flows/windows/hpx_rebranding/` → page_object, `resources/ui_map/windows/hpx_rebranding/` → locator, `resources/test_data/hpx_rebranding/` → test_data.
- Timeouts: `STARTUP_TIMEOUT_S=120`, `POLL_INTERVAL_S=5` (same discipline as the existing tool).

### service_manager.py
- `is_healthy()`: `GET /actuator/health` expecting 200/`{"status":"UP"}`, 3s timeout, ConnectionError → False.
- `ensure_service()`: if healthy, reuse the running instance (improvement over the old tool, which always starts the JAR). Else pre-flight `java -version` + `JAR_PATH.exists()` with actionable errors, then `subprocess.Popen(["java","-jar",JAR_PATH], cwd=REPO_ROOT)` with stdout/stderr → `test2/reports/indexer_service.log`, poll health every 2s up to 120s.
- `stop_service(proc)`: terminate only if we started it.

### index_manager.py
- `needs_reindex()` decision: (1) missing manifest/shards → reindex; (2) diff manifest `files[*].blobSha` vs `git ls-tree -r HEAD` plus `git status --porcelain`, scoped to the four LAYER_RULES roots → reindex if changed; (3) cheap fallback: HEAD commit date vs manifest `lastRun`. Log (don't fail on) the manifest-branch=main vs checkout=feature_sushree mismatch.
- `trigger_index()`: `POST /api/index` with `{"source":"local","destination":"lucene","repoPath":REPO_PATH,"userPrincipal":...,"isPurposeRequired":false,"isChunkSummaryRequired":false,"summariseTestsOnly":false}` (fast flags by default; CLI-overridable), then poll `GET /api/index/progress?owner=local&repo=MobileApps-main&branch=main` every 5s until COMPLETED/FAILED.
- After any re-index, re-read the manifest and update the identity used for search in case the service keys the index per-branch.

### search_client.py
- Thin `requests.Session` wrapper (requests is already in requirements.txt).
- `search(query)` → `POST /api/search` with the exact Postman body shape; normalize results into a `Chunk` dataclass (filePath, startLine, endLine, name, chunkType, isTestFile, score-if-present). Defensive parsing — response schema is only known from the collection; log-and-skip unknown shapes.
- Query strategy: 2–3 queries per defect — title verbatim; extracted identifiers/quoted strings from description + stack trace; failing assertion message. Union results, keep per-query provenance.
- `analyse(defect)` → `POST /api/analyse` with title/description/stackTrace/priority; capture `analysisId`. **Optional enrichment** (`--no-analyse` flag) — workflow is complete on `/api/search` alone.
- `send_feedback(analysis_id, ...)` and `get_accuracy()` for the validation loop.

### impact_analyzer.py
- `classify(chunk)`: prefix-match against LAYER_RULES; everything else → "other / out-of-scope" (e.g., iOS bell tests that will also match the query).
- `rank()`: API score if present, else (#queries hitting the file) × (#chunks), boosted by defect keywords in path; `/api/analyse` suspected files get a top-rank boost.
- **Cross-layer expansion** (the key value-add, deterministic via the page-object pattern): for each hit locator key in `ui_map` JSON, grep `libs/flows/windows/hpx_rebranding/` for that key string; for each hit page-object method, grep `Framework/` tests for callers. Pure stdlib, read-only. Guarantees locator → page object → test coverage even if Lucene returns only one layer.
- Output `ImpactSet`: per-layer `{file, lines, symbols, evidence, suggested_action}`.

### report_generator.py
- Writes `test2/reports/<defect_id>_impact_report.md`: defect summary | index status (lastRun, reindexed?) | queries issued | ranked impacted files grouped by layer with evidence | proposed fix per file | validation checklist | analysisId. Dumps raw search/analyse JSON alongside. Only module that writes files, only under `test2/reports/`.

### run_workflow.py
- `python test2/run_workflow.py defects/DEFECT-1042_bell_signin_rename.json [--force-reindex] [--no-analyse] [--keep-service]`
- Sequence: load defect → ensure_service → verify_or_refresh index → search×N + analyse → impact analysis → write report → print report path + top files → stop service if we started it. Exit codes 0/2 (index failed)/3 (service unreachable).

## Sample defect — DEFECT-1042 (defects/DEFECT-1042_bell_signin_rename.json)

Simulated Jira ticket: *"Bell notification panel: 'Sign in / Create account' button renamed to 'Sign in' — automation fails to find sign-in button."* Description names the locator key `notifications_panel_sign_in_btn`, the old xpath, and the AutomationId; `stack_trace` is a realistic pytest failure pointing at `test_suite_01...py::test_03` and `bell_icon.py:19`. All identifiers verified present in indexed files, so `/api/search` will hit `bell_icon.json`, `bell_icon.py`, and suites 01/02/04.

**Demo fix (applied in-place, guided by the report — no auto-patching in v1):**
1. `resources/ui_map/windows/hpx_rebranding/bell_icon.json` — `notifications_panel_sign_in_btn`: xpath becomes a fallback list `["//Button[@Name='Sign in']", "//Button[@Name='Sign in / Create account']"]`; append new AutomationId to the existing id list (file already uses list-valued ids).
2. `libs/flows/windows/hpx_rebranding/bell_icon.py` — **no change needed** (key indirection); report states "verified unaffected", demonstrating the analyzer distinguishes touched vs impacted.
3. Test suites 01/02/04 — no functional change unless a literal `Sign in / Create account` string is found in tests/test_data (analyzer greps to confirm).
4. App-code path: when `/api/analyse` points at product code instead of automation code, the report routes it to a "needs dev fix" section instead of proposing automation edits.

## BUGFIX_WORKFLOW.md (the in-repo plan document)

Sections: purpose/scope · architecture diagram (defect → service → index → search/analyse → impact report → in-place fix → validation) with component table · prerequisites (Java 17+, jar, port 8080) · service endpoints with exact request bodies · index freshness policy + branch caveat · running the workflow · reading the impact report (layer model, ranking) · applying fixes per layer with the DEFECT-1042 worked example · validation checklist + accuracy/feedback loop · limitations & future work (remote-rig execution, auto-patch, real Jira intake, retiring old tool config) · troubleshooting.

## Verification

1. **Service**: `curl http://localhost:8080/actuator/health` → `{"status":"UP"}` after `service_manager` starts the JAR.
2. **Index**: `POST /api/index/status` → COMPLETED; manifest `lastRun` sane; `GET /api/index/accuracy` recorded in report.
3. **Search acceptance test** (proves the pipeline): DEFECT-1042 queries must return `resources/ui_map/windows/hpx_rebranding/bell_icon.json` AND `libs/flows/windows/hpx_rebranding/bell_icon.py` AND ≥1 of suites 01/02/04 — asserted by `run_workflow.py --validate`.
4. **Post-fix static checks**: `python -m json.tool` on the edited locator JSON; `python -m py_compile` on touched .py; `python -m pytest tests/windows/hpx_rebranding/Framework/bell_notifications/ --collect-only -q` (imports/conftest chain still clean; full UI execution needs the remote Windows rig — documented limitation).
5. **Feedback loop**: `POST /api/analyse/{analysisId}/feedback` with the confirmed file.

## Implementation order (~11h total)

1. `config.py` + sample defect JSON (0.5h)
2. `service_manager.py` — port pattern from `Indexing_API_Trigger_ToolV3_CONFIG.py`, corrected config (1h)
3. `index_manager.py` (1.5h)
4. `search_client.py` — run against live JAR early to pin response schemas (1.5h)
5. `impact_analyzer.py` (2h)
6. `report_generator.py` + `run_workflow.py` (1.5h)
7. End-to-end demo run, tune queries, capture report (1h)
8. `BUGFIX_WORKFLOW.md` (1.5h)
9. Validation pass + demo fix application + feedback round-trip (0.5h)

## Risks

- **JAR/Java**: Spring Boot jar likely needs Java 17+ — pre-flight check, service log captured for diagnosis; health-check-first avoids port-8080 double-start.
- **Branch identity**: index built for `main`, checkout is `feature_sushree`. Keep `BRANCH="main"` (matches manifest) in one config place; blob-SHA freshness check detects drift; after re-index, read back manifest identity.
- **Search noise**: iOS bell tests will match — layer classifier marks them out-of-scope; cross-layer grep expansion anchors the report deterministically.
- **`/api/analyse` behavior unknown** (possibly LLM-backed/slow): optional via `--no-analyse`.
- **Re-index duration** on 4k+ files: default to skipping when relevant blob SHAs unchanged; `--force-reindex` for the demo.

## Critical existing files (read/reused, not edited)

- `tests/windows/hpx_rebranding/Framework/bell_notifications/Indexing_API_Trigger_ToolV3_CONFIG.py` — JAR start/poll pattern source
- `Code-Indexing Version4.json` — endpoint contracts
- `.code_index/index_manifest.json` — freshness inputs
- `resources/ui_map/windows/hpx_rebranding/bell_icon.json`, `libs/flows/windows/hpx_rebranding/bell_icon.py`, `Framework/bell_notifications/test_suite_{01,02,04}*.py` — sample-defect fix targets