"""
indexer.py
Core indexing utility and API client engine.
Handles platform requests, session management, and metrics retrieval.
"""

import sys

try:
    import requests
except ModuleNotFoundError:
    raise SystemExit(
        "Missing dependency 'requests'. Install it with: pip install requests"
    )


class AavaPlatformIndexer:
    def __init__(self, config_dict):
        """
        Initializes the API client with credentials and structural endpoints from config.
        """
        self.config = config_dict
        self.base_url = (
            self.config.get("BASE_URL")
            or self.config.get("AAVA_API_BASE")
            or self.config.get("INDEXER_BASE_URL", "")
        ).rstrip("/")
        self.endpoint = (
            self.config.get("ENDPOINT")
            or self.config.get("METRICS_ENDPOINT")
            or ""
        ).strip()
        self.timeout = self.config.get("REQUEST_TIMEOUT", 30)
        self.session = requests.Session()
        self._setup_headers()

    def _setup_headers(self):
        """
        Constructs required authentication and content-type headers.
        """
        headers = dict(self.config.get("HEADERS") or {})

        # Inject Bearer token if API key exists and Authorization isn't explicitly set
        if not headers.get("Authorization") and self.config.get("AAVA_API_KEY"):
            headers["Authorization"] = f"Bearer {self.config['AAVA_API_KEY']}"

        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        self.session.headers.update(headers)

    def build_url(self, exec_id):
        """
        Smart URL Builder. Determines if the endpoint uses query parameters
        (e.g., ?executionId=) or standard path components (e.g., /execution/id).
        """
        path = self.endpoint
        if not path.startswith("/"):
            path = "/" + path

        if "?" in path:
            return f"{self.base_url}{path}{exec_id}"
        else:
            if not path.endswith("/"):
                path += "/"
            return f"{self.base_url}{path}{exec_id}"

    def get_execution_metrics(self, exec_id):
        """
        Executes a GET call to retrieve performance metrics for a specific execution ID.
        Returns a tuple of (success_boolean, parsed_data_or_error_message).
        """
        url = self.build_url(exec_id)
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            try:
                data = response.json()
                return True, data
            except ValueError:
                return False, f"Invalid JSON response format. Raw: {response.text[:200]}"

        except requests.exceptions.RequestException as e:
            error_msg = f"Network communication error: {e}"
            if hasattr(e, "response") and e.response is not None:
                error_msg += f" | Response Body: {e.response.text[:200]}"
            return False, error_msg

    def parse_metrics(self, data):
        """
        Defensively extracts and structures cost, timeline, and token footprints.
        Returns a dictionary containing floats and integers.
        """
        if not isinstance(data, dict):
            return {"cost": 0.0, "time_taken": 0.0, "tokens": 0}

        # Safe fallback logic to prevent float parsing errors from blank/Null payloads
        cost = data.get("total_cost", 0.0)
        time_taken = data.get("time_taken", 0.0)
        tokens = data.get("total_tokens", 0)

        return {
            "cost": float(cost or 0.0),
            "time_taken": float(time_taken or 0.0),
            "tokens": int(tokens or 0),
        }
