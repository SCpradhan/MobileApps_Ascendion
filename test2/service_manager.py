"""Lifecycle for the code-indexer service (code-indexer-2.0.0.jar on port 8080).

Start/poll pattern adapted from
tests/windows/hpx_rebranding/Framework/bell_notifications/Indexing_API_Trigger_ToolV3_CONFIG.py,
with two changes: health-check-first so an already-running instance is reused
instead of double-started, and corrected jar path (repo-root 2.0.0 jar).
"""
import subprocess
import sys
import time

import requests

import config


def is_healthy(timeout=3):
    try:
        resp = requests.get(config.HEALTH_URL, timeout=timeout)
        return resp.status_code == 200 and resp.json().get("status") == "UP"
    except (requests.exceptions.RequestException, ValueError):
        return False


def _preflight():
    if not config.JAR_PATH.exists():
        raise RuntimeError(
            f"Indexer jar not found at {config.JAR_PATH}. "
            "Expected code-indexer-2.0.0.jar at the repo root."
        )
    try:
        subprocess.run(["java", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Java is not available on PATH. The indexer is a Spring Boot jar "
            "(Java 17+ recommended). Install a JDK and retry."
        ) from exc


def ensure_service():
    """Return a Popen handle if we started the jar, or None if one was already up."""
    if is_healthy():
        print(f"Indexer service already running at {config.BASE_URL} - reusing it.")
        return None

    _preflight()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(config.SERVICE_LOG, "w")
    print(f"Starting {config.JAR_PATH.name} (logs -> {config.SERVICE_LOG})")
    process = subprocess.Popen(
        ["java", "-jar", str(config.JAR_PATH),
         f"--spring.profiles.active={config.SPRING_PROFILE}"],
        cwd=config.REPO_ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    process._workflow_log_file = log_file

    deadline = time.time() + config.STARTUP_TIMEOUT_S
    while time.time() < deadline:
        if is_healthy():
            print("Indexer service is UP.")
            return process
        if process.poll() is not None:
            log_file.close()
            raise RuntimeError(
                f"Indexer jar exited during startup (code {process.returncode}). "
                f"See {config.SERVICE_LOG}."
            )
        time.sleep(2)

    process.terminate()
    log_file.close()
    raise RuntimeError(
        f"Timed out after {config.STARTUP_TIMEOUT_S}s waiting for "
        f"{config.HEALTH_URL}. See {config.SERVICE_LOG}."
    )


def stop_service(process):
    """Terminate the jar only if ensure_service() started it (process is not None)."""
    if process is None:
        return
    print("Stopping indexer service (started by this run).")
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file = getattr(process, "_workflow_log_file", None)
    if log_file:
        log_file.close()


if __name__ == "__main__":
    proc = ensure_service()
    print(f"healthy: {is_healthy()}")
    if "--stop" in sys.argv:
        stop_service(proc)
    elif proc is not None:
        print("Service left running (started by this smoke run); stop with --stop or kill the java process.")
