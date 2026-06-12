"""Single source of truth for the bug-fix workflow: paths, service URL, repo identity.

Supersedes the stale config in
tests/windows/hpx_rebranding/Framework/bell_notifications/Indexing_API_Trigger_ToolV3_CONFIG.py
(which points at code-indexer-1.0.0.jar in a different directory and at a
MobileApps-feature_sushree sibling checkout). Do not edit that file; this one wins.
"""
from pathlib import Path

# test2/ sits directly under the repo root, so resolve dynamically.
REPO_ROOT = Path(__file__).resolve().parent.parent

JAR_PATH = REPO_ROOT / "code-indexer-2.0.0.jar"
# The jar's default profile requires Mongo/JDBC/AWS credentials; the embedded
# "offline" profile (BOOT-INF/classes/application-offline.yml) runs fully local:
# Lucene storage, in-memory BM25, no external services.
SPRING_PROFILE = "offline"
INDEX_DIR = REPO_ROOT / ".code_index"
MANIFEST_PATH = INDEX_DIR / "index_manifest.json"
SHARDS_DIR = INDEX_DIR / "shards"

BASE_URL = "http://localhost:8080"
HEALTH_URL = f"{BASE_URL}/actuator/health"

# Repo identity used by the indexing service. The Postman collection
# (Code-Indexing Version4.json) uses owner=local&repo=MobileApps-main&branch=main;
# the manifest records repo NavneetBN47/MobileApps, branch main. Search falls back
# through IDENTITY_FALLBACKS if the primary identity returns nothing.
OWNER = "local"
REPO = "MobileApps-main"
BRANCH = "main"
SOURCE = "local"
DESTINATION = "lucene"
REPO_PATH = str(REPO_ROOT)
USER_PRINCIPAL = "pribiswal7@gmail.com"

IDENTITY_FALLBACKS = [
    {"owner": "local", "repo": "MobileApps-main", "branch": "main"},
    {"owner": "NavneetBN47", "repo": "MobileApps", "branch": "main"},
    {"owner": "NavneetBN47", "repo": "MobileApps", "branch": "feature_sushree"},
    {"owner": "local", "repo": REPO_ROOT.name, "branch": "main"},
]

REQUEST_TIMEOUT_S = 30
STARTUP_TIMEOUT_S = 120
POLL_INTERVAL_S = 5
SEARCH_TIMEOUT_S = 120      # lucene search may be slow on first query
ANALYSE_TIMEOUT_S = 300     # /api/analyse may be LLM-backed

TEST2_DIR = REPO_ROOT / "test2"
DEFECTS_DIR = TEST2_DIR / "defects"
REPORTS_DIR = TEST2_DIR / "reports"
SERVICE_LOG = REPORTS_DIR / "indexer_service.log"

# Ordered prefix -> layer rules used to classify search hits. Anything that
# matches none of these is reported as "other" (out of scope for the Windows
# hpx_rebranding automation, e.g. iOS bell tests).
LAYER_RULES = [
    ("locator", "resources/ui_map/windows/hpx_rebranding/"),
    ("page_object", "libs/flows/windows/hpx_rebranding/"),
    ("test", "tests/windows/hpx_rebranding/Framework/"),
    ("test_data", "resources/test_data/hpx_rebranding/"),
]

# Roots whose changes make the index stale for this workflow.
RELEVANT_ROOTS = tuple(prefix for _, prefix in LAYER_RULES)
