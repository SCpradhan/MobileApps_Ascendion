"""Index freshness check and refresh against the code-indexer service.

Freshness is decided by comparing the manifest's per-file blobSha map against
the current git HEAD (git ls-tree), scoped to the automation roots the workflow
cares about (config.RELEVANT_ROOTS). Uncommitted/untracked files are reported
as a warning but do not force a re-index on their own - the working tree
permanently carries untracked tooling files.
"""
import json
import subprocess
import time

import requests

import config


def load_manifest():
    if not config.MANIFEST_PATH.exists():
        return None
    with open(config.MANIFEST_PATH) as f:
        return json.load(f)


def index_status_summary():
    manifest = load_manifest()
    shard_count = len(list(config.SHARDS_DIR.glob("*.json"))) if config.SHARDS_DIR.exists() else 0
    if manifest is None:
        return {"present": False, "shards": shard_count}
    return {
        "present": True,
        "lastRun": manifest.get("lastRun"),
        "repo": manifest.get("repo"),
        "branch": manifest.get("branch"),
        "fileCount": len(manifest.get("files", {})),
        "shards": shard_count,
    }


def _git_head_blobs():
    """Map of repo-relative path -> blob sha at HEAD, scoped to relevant roots."""
    out = subprocess.run(
        ["git", "-C", str(config.REPO_ROOT), "ls-tree", "-r", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    blobs = {}
    for line in out.splitlines():
        # format: <mode> blob <sha>\t<path>
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob" and path.startswith(config.RELEVANT_ROOTS):
            blobs[path] = parts[2]
    return blobs


def _dirty_relevant_files():
    out = subprocess.run(
        ["git", "-C", str(config.REPO_ROOT), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    dirty = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith(config.RELEVANT_ROOTS):
            dirty.append((line[:2].strip(), path))
    return dirty


def _manifest_blob(entry):
    if isinstance(entry, dict):
        return entry.get("blobSha")
    return None


def service_has_index():
    """Probe the running service; its store (e.g. Lucene in the offline
    profile) is separate from the .code_index shards on disk, so a manifest
    on disk does not guarantee the service can answer searches."""
    try:
        resp = requests.post(
            f"{config.BASE_URL}/api/search",
            json={"source": config.SOURCE, "destination": config.DESTINATION,
                  "owner": config.OWNER, "repo": config.REPO,
                  "branch": config.BRANCH, "repoPath": config.REPO_PATH,
                  "query": "index presence probe"},
            timeout=config.SEARCH_TIMEOUT_S)
        return resp.status_code != 404
    except requests.exceptions.RequestException:
        return True  # can't tell; don't force a re-index on a flaky probe


def needs_reindex():
    """Return (bool, reason). Conservative: re-index only on hard evidence."""
    manifest = load_manifest()
    if manifest is None:
        return True, f"no index manifest at {config.MANIFEST_PATH}"
    if not config.SHARDS_DIR.exists() or not any(config.SHARDS_DIR.glob("*.json")):
        return True, "shards directory is missing or empty"
    if not service_has_index():
        return True, (f"service has no index for {config.OWNER}/{config.REPO}"
                      f"@{config.BRANCH} in its {config.DESTINATION} store")

    if manifest.get("branch") and manifest.get("branch") != _current_branch():
        print(f"NOTE: index was built for branch '{manifest.get('branch')}', "
              f"checkout is '{_current_branch()}'. Continuing with the existing index.")

    manifest_files = manifest.get("files", {})
    head_blobs = _git_head_blobs()
    changed = []
    for path, sha in head_blobs.items():
        recorded = _manifest_blob(manifest_files.get(path))
        if recorded is not None and recorded != sha:
            changed.append(path)
    if changed:
        return True, (f"{len(changed)} indexed file(s) under relevant roots changed "
                      f"since lastRun {manifest.get('lastRun')} (e.g. {changed[0]})")

    dirty = _dirty_relevant_files()
    if dirty:
        print(f"WARNING: {len(dirty)} uncommitted file(s) under relevant roots are not "
              "reflected in the index (use --force-reindex to refresh). "
              f"e.g. {dirty[0][1]}")
    return False, "indexed blob SHAs match git HEAD for all relevant roots"


def _current_branch():
    return subprocess.run(
        ["git", "-C", str(config.REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def trigger_index(purpose=False, chunk_summaries=False, tests_only=False):
    payload = {
        "owner": config.OWNER,
        "repo": config.REPO,
        "branch": config.BRANCH,
        "source": config.SOURCE,
        "destination": config.DESTINATION,
        "repoPath": config.REPO_PATH,
        "userPrincipal": config.USER_PRINCIPAL,
        "useClone": False,
        "isPurposeRequired": purpose,
        "isChunkSummaryRequired": chunk_summaries,
        "summariseTestsOnly": tests_only,
    }
    url = f"{config.BASE_URL}/api/index"
    print(f"Triggering re-index: POST {url}")
    resp = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def poll_index_progress(max_wait_s=3600):
    url = (f"{config.BASE_URL}/api/index/progress"
           f"?owner={config.OWNER}&repo={config.REPO}&branch={config.BRANCH}")
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            data = requests.get(url, timeout=config.REQUEST_TIMEOUT_S).json()
            state = data.get("state")
            print(f"  index progress: {state} | "
                  f"step {data.get('currentStep')}/{data.get('totalSteps')} "
                  f"({data.get('currentStepName')}) | {data.get('percentComplete')}%")
            if state == "COMPLETED":
                return data
            if state in ("FAILED", "ERROR", "ABORTED"):
                raise RuntimeError(f"Indexing {state}: {data.get('errorMessage')}")
        except requests.exceptions.RequestException as exc:
            print(f"  progress poll error (will retry): {exc}")
        time.sleep(config.POLL_INTERVAL_S)
    raise RuntimeError(f"Indexing did not complete within {max_wait_s}s")


def verify_or_refresh(force=False):
    """Main entry: returns a dict describing the final index state."""
    reindex, reason = (True, "forced via --force-reindex") if force else needs_reindex()
    print(f"Index check: {'REFRESH' if reindex else 'OK'} - {reason}")
    refreshed = False
    if reindex:
        trigger_index()
        poll_index_progress()
        refreshed = True
    summary = index_status_summary()
    summary.update({"refreshed": refreshed, "decision_reason": reason})
    return summary


if __name__ == "__main__":
    import sys
    print(json.dumps(verify_or_refresh(force="--force-reindex" in sys.argv), indent=2))
