# QA Bug-Fix Workflow — Jira Defect → Index Search → Impacted Files → Test Fix

Technical plan and runnable tooling for handling a QA defect against the
MobileApps automation repo using the local code-indexing/search service.

```
Jira defect (JSON) ──► indexer service (code-indexer-2.0.0.jar :8080)
                          │  verify/refresh .code_index  (POST /api/index)
                          ▼
                       POST /api/search  (+ optional POST /api/analyse)
                          │  relevant chunks / suspected files
                          ▼
                       impact analysis  (layer mapping + cross-layer expansion)
                          │
                          ▼
                       test2/reports/<DEFECT>_impact_report.md
                          │  human/agent applies fixes in place
                          ▼
                       tests/…  libs/flows/…  resources/ui_map/…
                          │
                          ▼
                       validation (health, collect-only, static checks, feedback API)
```

## 1. Purpose & scope

When QA logs a defect, this workflow finds the impacted **automation assets**
(test suites, page objects, UI locators, test data) using the already-built
code index, proposes the fixes, and defines how to validate them.
Application-code changes are only routed (flagged as "needs dev fix"), never
auto-edited — most UI defects of this kind resolve in the automation layers.

Scope of v1: Windows `hpx_rebranding` suites. `test2/` is the workflow
workspace; **fixes are applied in place** under `tests/`, `libs/`, `resources/`.

## 2. Components

| File | Responsibility |
|---|---|
| `config.py` | Single source of truth: repo root (resolved dynamically), jar path, service URL, repo identity, layer rules |
| `service_manager.py` | Health check (`GET /actuator/health`), start/stop `code-indexer-2.0.0.jar` with the `offline` Spring profile, reuse a running instance |
| `index_manager.py` | Index freshness (manifest blobSha vs `git ls-tree HEAD`), `POST /api/index`, progress polling |
| `search_client.py` | `POST /api/search` (with identity fallback), `POST /api/analyse`, feedback + accuracy endpoints, query construction from the defect |
| `impact_analyzer.py` | Classify hits into layers, rank, deterministic cross-layer expansion (locator key → page object → test) |
| `report_generator.py` | Markdown impact report + raw API dump into `test2/reports/` |
| `run_workflow.py` | CLI orchestrator, exit codes 0 / 2 (index failed) / 3 (service unreachable) |
| `defects/DEFECT-1042_bell_signin_rename.json` | Sample simulated Jira ticket (bell-panel sign-in button rename) |

Supersedes the stale config in
`tests/windows/hpx_rebranding/Framework/bell_notifications/Indexing_API_Trigger_ToolV3_CONFIG.py`
(old 1.0.0 jar path, wrong checkout path). That file is kept untouched as the
pattern source. The AAVA cloud KB pipeline (`generate_index_4.py`,
`indexer.py`, `index_outputs/`) is a separate flow and is **not** used here.

## 3. Prerequisites

- Java (JDK 17+; verified working on OpenJDK 22) on PATH.
- `code-indexer-2.0.0.jar` at the repo root.
- Python with `requests` — the repo `.venv` already has it.
- Port 8080 free, or an indexer instance already running (it will be reused).

**Important — Spring profile.** The jar's default profile requires
MongoDB/JDBC/AWS credentials and fails at startup with *"Failed to configure a
DataSource"*. The embedded `offline` profile runs fully local (Lucene storage,
in-memory BM25, no external services). `service_manager.py` always starts the
jar with `--spring.profiles.active=offline`.

## 4. Service endpoints used

From the Postman collection `Code-Indexing Version4.json` at the repo root:

| Endpoint | Used for |
|---|---|
| `GET /actuator/health` | readiness gate before anything else |
| `POST /api/index` | re-index; body: `owner, repo, branch, source:"local", destination:"lucene", repoPath, userPrincipal, useClone:false, isPurposeRequired, isChunkSummaryRequired, summariseTestsOnly` |
| `GET /api/index/progress?owner&repo&branch` | poll until `state` is `COMPLETED`/`FAILED` (fields: `currentStep/totalSteps/currentStepName/percentComplete/errorMessage`) |
| `POST /api/search` | body: `source, destination, owner, repo, branch, repoPath, query` → chunk list |
| `POST /api/analyse` | optional enrichment; body: `title, description, stackTrace, priority, source, repoPath, destination` |
| `POST /api/analyse/{analysisId}/feedback` | close the loop after the fix is confirmed |
| `GET /api/index/accuracy` | accuracy metric for the report |

Index artifacts live in `.code_index/` (manifest + 38 AST-chunked shards;
manifest records per-file `blobSha`, `chunkCount`, `isTestFile`, `lastRun`).

## 5. Index freshness policy

`index_manager.needs_reindex()` is conservative — re-index only on hard evidence:

1. Missing manifest or empty `shards/` → re-index.
2. Any **tracked** file under the relevant roots
   (`tests/windows/hpx_rebranding/Framework/`, `libs/flows/windows/hpx_rebranding/`,
   `resources/ui_map/windows/hpx_rebranding/`, `resources/test_data/hpx_rebranding/`)
   whose `git ls-tree HEAD` blob SHA differs from the manifest's recorded
   `blobSha` → re-index, with the changed file named in the reason.
3. Uncommitted/untracked files under those roots only produce a **warning**
   (the working tree permanently carries untracked tooling files); use
   `--force-reindex` when they matter.

Branch caveat: the existing index was built for branch `main` while the
checkout is `feature_sushree`. The mismatch is logged, not fatal — search
identity is config-driven (`config.IDENTITY_FALLBACKS` tries
`local/MobileApps-main/main` first, then the manifest identity).

## 6. Running the workflow

```bash
cd <repo-root>/test2
../.venv/bin/python run_workflow.py defects/DEFECT-1042_bell_signin_rename.json \
    [--force-reindex] [--no-analyse] [--keep-service] [--validate]
```

- `--force-reindex` — re-index regardless of the freshness check (use for demos
  or after uncommitted locator edits).
- `--no-analyse` — skip `/api/analyse` (it can be slow/LLM-backed); the
  workflow is complete on `/api/search` alone.
- `--keep-service` — leave the jar running for follow-up queries.
- `--validate` — assert the impact set covers locator + page object + ≥1 test
  suite (the workflow's own acceptance test; exit 1 if not).

Each module also runs standalone for stepwise demos
(`python service_manager.py`, `python index_manager.py`,
`python search_client.py <defect.json>`, `python impact_analyzer.py <defect.json>`).

## 7. Reading the impact report

Reports land in `test2/reports/<DEFECT>_impact_report.md` (plus
`<DEFECT>_raw.json` with the raw API payloads). Files are grouped by layer:

- **locator** (`resources/ui_map/...`) — usually the primary fix for UI-rename
  defects; locators are JSON keys with `id`/`xpath` values, both may be
  fallback **lists**.
- **page_object** (`libs/flows/...`) — methods reference locator *keys*
  (`self.driver.wait_for_object("notifications_panel_sign_in_btn")`), so they
  usually need **no change**; the report says so explicitly when true.
- **test** (`tests/.../Framework/...`) — change only if a test asserts the
  literal UI text that changed.
- **test_data** / **other** — stored UI literals; out-of-scope hits (e.g. iOS
  bell tests) are listed under "other" for visibility.

Ranking: API relevance score when returned, otherwise query-coverage ×
chunk-density, with boosts for `/api/analyse`-flagged files and defect
keywords in the path. Independently of search, **cross-layer expansion**
deterministically walks locator key → page-object usages → test callers via
plain string search, so all three layers are always covered.

## 8. Worked example — DEFECT-1042

Defect: bell-panel sign-in button renamed `'Sign in / Create account'` →
`'Sign in'`; suites time out on `notifications_panel_sign_in_btn`.

Fix, per the generated report:

1. **`resources/ui_map/windows/hpx_rebranding/bell_icon.json`** (primary) —
   key `notifications_panel_sign_in_btn`: make `xpath` a fallback list
   `["//Button[@Name='Sign in']", "//Button[@Name='Sign in / Create account']"]`
   and append the new AutomationId to the existing `id` list. Old values stay
   as fallbacks so older app builds keep passing.
2. **`libs/flows/windows/hpx_rebranding/bell_icon.py`** — no change
   (key indirection); listed as impacted-but-unchanged.
3. **Suites 01/02/04** under `Framework/bell_notifications/` — assertion
   *messages* mention the button but no literal label is asserted → no change;
   re-run after the locator fix.
4. App code — none; the rename is intended product behavior.

## 9. Validation checklist

1. `curl http://localhost:8080/actuator/health` → `{"status":"UP"}`.
2. `run_workflow.py … --validate` exits 0 (search/expansion found locator +
   page object + test suites).
3. After applying edits:
   - `python -m json.tool resources/ui_map/windows/hpx_rebranding/bell_icon.json`
   - `python -m py_compile` on any touched `.py`
   - `python -m pytest tests/windows/hpx_rebranding/Framework/bell_notifications/ --collect-only -q`
     (requires the `SAF` framework package on `PYTHONPATH` — see
     Troubleshooting; not installed in this dev `.venv`, so treat this step
     as a CI/remote-rig check rather than a local one)
4. `POST /api/analyse/{analysisId}/feedback` with the confirmed file —
   improves future analyses; `GET /api/index/accuracy` before/after.
5. Full UI execution requires the remote Windows rig (the conftest chain does
   SSH + driver setup); local exit criteria is collect-only + static checks.

## 10. Limitations & future work

- No auto-patching in v1 — the report proposes, a human/agent applies.
- Real Jira intake: swap the defect-JSON loader for a Jira REST pull; the
  Postman collection already documents a JIRA-source `POST /api/index` body.
- Remote-rig execution hook (run the impacted suites automatically post-fix).
- `/api/search` supports agent-side `intent`/`hydeSnippet` fields per the
  jar's offline-profile notes — richer query planning is a cheap upgrade.
- Retire the stale `Indexing_API_Trigger_ToolV3_CONFIG.py` config once this
  workflow is adopted.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Jar exits at startup, "Failed to configure a DataSource" | Default Spring profile needs Mongo/JDBC. Use the `offline` profile (service_manager does this automatically). |
| Timeout waiting for health | Check `test2/reports/indexer_service.log`; port 8080 may be taken by something unhealthy. |
| Search returns 0 chunks | Identity mismatch — see `config.IDENTITY_FALLBACKS`; or the index is stale → `--force-reindex`. |
| `/api/analyse` hangs or 5xx | LLM credentials absent in offline profile; run with `--no-analyse`. |
| Progress poll stuck < 100% | Watch `indexer_service.log`; large repos take minutes. FAILED state raises with `errorMessage`. |
| `--collect-only` fails with `ModuleNotFoundError: No module named 'SAF'` | `tests/conftest.py` imports the `SAF` automation framework package, which lives outside this repo (provided on the test rig / CI image, not in `.venv`). Not a regression from a fix — run collect-only on the rig/CI, or treat `json.tool` + `py_compile` as the local exit criteria. |
