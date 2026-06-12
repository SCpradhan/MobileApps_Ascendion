import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:
    raise SystemExit(
        "Missing dependency 'requests'. Install it with: pip install requests"
    )

from app_config import CONFIG


class TeeLogger:
    def __init__(self, *paths: Path):
        self.paths = paths
        self.handles = []

    def __enter__(self):
        for path in self.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handles.append(path.open("w", encoding="utf-8"))
        return self

    def __exit__(self, exc_type, exc, tb):
        for handle in self.handles:
            handle.close()

    def write(self, message: str) -> None:
        print(message)
        for handle in self.handles:
            handle.write(message + "\n")
            handle.flush()


def get_log_paths() -> tuple[Path, Path]:
    fixed_log = Path(CONFIG.get("LOG_FILE_PATH", "logs/usage_analyzer.log"))
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    timestamped_log = fixed_log.with_name(f"usage_analyzer_{timestamp}.log")
    return fixed_log, timestamped_log


def validate_config(cfg: dict[str, Any]) -> bool:
    if not isinstance(cfg, dict):
        print("Error: app_config.CONFIG must be a dictionary.")
        return False

    if not cfg.get("ENDPOINT"):
        print("Error: ENDPOINT is missing from app_config.")
        return False

    exec_ids = cfg.get("EXECUTION_IDS")
    if not isinstance(exec_ids, list) or not exec_ids:
        print("Error: EXECUTION_IDS must be a non-empty list in app_config.")
        return False

    base_url = cfg.get("BASE_URL") or cfg.get("AAVA_API_BASE")
    if not base_url:
        print("Error: BASE_URL or AAVA_API_BASE is missing from app_config.")
        return False

    endpoint = str(cfg.get("ENDPOINT", "")).strip()
    if "/console/" in endpoint or endpoint.startswith("/console/"):
        print("Error: ENDPOINT points to a Console UI page, not a JSON API endpoint.")
        print("Current ENDPOINT:", endpoint)
        print("Use the backend API route that returns execution metrics as JSON.")
        return False

    return True


def build_url(base_url, endpoint, exec_id):
    base = base_url.rstrip("/")
    path = endpoint.strip()
    
    # If the endpoint contains query parameters, do not force standard path slash conventions
    if "?" in path:
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}{exec_id}"
    else:
        # Standard path assembly (e.g. /v1/execution/ID)
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path = path + "/"
        return f"{base}{path}{exec_id}"


def fetch_usage_data():
    if not validate_config(CONFIG):
        return 1

    base_url = CONFIG.get("BASE_URL") or CONFIG.get("AAVA_API_BASE")
    endpoint = CONFIG["ENDPOINT"].strip()
    execution_ids = CONFIG["EXECUTION_IDS"]

    headers = dict(CONFIG.get("HEADERS") or {})
    api_key = os.getenv("AAVA_API_KEY") or CONFIG.get("AAVA_API_KEY")
    if not headers.get("Authorization") and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    total_cost = 0.0
    total_time = 0.0
    total_tokens = 0

    fixed_log, timestamped_log = get_log_paths()

    with TeeLogger(fixed_log, timestamped_log) as logger:
        logger.write(f"Run started: {datetime.now().isoformat(timespec='seconds')}")
        logger.write(f"Fixed log: {fixed_log.resolve()}")
        logger.write(f"Timestamped log: {timestamped_log.resolve()}")
        logger.write("")
        logger.write(f"{'Execution ID':<40} | {'Cost':<10} | {'Time (s)':<10} | {'Tokens':<10}")
        logger.write("-" * 80)

        for exec_id in execution_ids:
            exec_id = str(exec_id).strip()
            url = build_url(base_url, endpoint, exec_id)

            try:
                logger.write(f"[DEBUG] Fetching URL: {url}")
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=CONFIG.get("REQUEST_TIMEOUT", 30),
                )
                response.raise_for_status()

                content_type = (response.headers.get("Content-Type") or "").lower()
                if "html" in content_type:
                    logger.write(f"Error fetching {exec_id}: Endpoint returned HTML, not JSON.")
                    logger.write("This usually means ENDPOINT is a frontend route instead of an API route.")
                    logger.write(f"URL used: {url}")
                    continue

                try:
                    data = response.json()
                except ValueError:
                    logger.write(f"Error fetching {exec_id}: Response body was not valid JSON.")
                    logger.write(f"Status code: {response.status_code}")
                    logger.write(f"Response text snippet: {response.text[:300]}")
                    continue

                payload = data.get("data", data)

                # Support both snake_case and camelCase response formats.
                cost = payload.get("total_cost", payload.get("totalCost", 0.0))
                time_taken = payload.get("time_taken", payload.get("totalTimeTaken", 0.0))
                tokens = payload.get("total_tokens", payload.get("totalTokens", 0))

                logger.write(f"{exec_id:<40} | {cost:<10.4f} | {time_taken:<10.2f} | {tokens:<10}")

                total_cost += float(cost or 0)
                total_time += float(time_taken or 0)
                total_tokens += int(tokens or 0)

            except requests.exceptions.RequestException as e:
                logger.write(f"Network/API Error fetching {exec_id}: {e}")
                if hasattr(e, "response") and e.response is not None:
                    logger.write(f"Server responded with body: {e.response.text[:300]}")

        logger.write("-" * 80)
        logger.write(f"{'TOTALS':<40} | {total_cost:<10.4f} | {total_time:<10.2f} | {total_tokens:<10}")
        logger.write("")
    return 0


if __name__ == "__main__":
    sys.exit(fetch_usage_data())
