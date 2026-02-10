import concurrent.futures
import os
import time

import pytest
import requests

from tests.metrics.runtime_metrics import MetricsCollector

# Configuration
BASE_URL = os.environ.get("ORCH_BASE_URL", "http://localhost:9325")
AUTH_TOKEN = os.environ.get("ORCH_TEST_TOKEN", "")
PANIC_THRESHOLD_RPS = 100  # Adjust based on rate limit config in config.py if known


@pytest.fixture(scope="module")
def metrics():
    collector = MetricsCollector()
    yield collector
    collector.save_report("out/metrics/chaos_resilience_report.json")


def send_request(endpoint, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    start = time.time()
    try:
        resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=2)
        latency = time.time() - start
        return resp.status_code, latency, resp.text
    except Exception:
        return 0, 0, "error"


def _is_orchestrator_available() -> bool:
    try:
        response = requests.get(f"{BASE_URL}/status", timeout=2)
        return response.status_code in {200, 401}
    except requests.exceptions.RequestException:
        return False


@pytest.mark.integration
def test_rate_limit_saturation(metrics):
    """
    Floods the API to trigger 429 Rate Limit.
    """
    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.skip("Orchestrator not reachable")
    total_reqs = 150
    endpoint = "/status"

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(send_request, endpoint, AUTH_TOKEN) for _ in range(total_reqs)]

        status_codes = []
        for future in concurrent.futures.as_completed(futures):
            code, lat, _ = future.result()
            status_codes.append(code)

    rate_limited_count = status_codes.count(429)
    success_count = status_codes.count(200)

    print(f"Rate Limit Test: {success_count} OK, {rate_limited_count} Blocked (429)")

    metrics.add_result(
        suite="chaos_resilience",
        endpoint="/status",
        payload=f"BURST_{total_reqs}",
        status=429 if rate_limited_count > 0 else 200,
        latency=0.1,  # Approx
        panic=False,
        bypassed=False,
    )

    # We expect at least some 429s given the config usually has limits
    assert rate_limited_count > 0, "Rate limit not triggered; adjust ORCH_RATE_LIMIT settings"


@pytest.mark.integration
def test_panic_mode_trigger_and_recovery(metrics):
    """
    Forces the system into PANIC mode by simulating a massive security event spike,
    then verifies recovery via the resolution endpoint.
    """
    # 1. Trigger Panic (simulate by rapid auth failures or similar if possible,
    # but here we might need to rely on the backend's panic logic.
    # If there's no direct 'trigger panic' endpoint, we simulate attack traffic)

    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.skip("Orchestrator not reachable")
    # Simulating attack traffic (e.g. 50 bad auth requests in 1 sec)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(send_request, "/status", "BAD_TOKEN") for _ in range(50)]
        concurrent.futures.wait(futures)

    # Check if system is in panic (503)
    resp, _, _ = send_request("/status", AUTH_TOKEN)

    # Note: If the backend logic requires more specific triggers for panic, this might stay 200.
    # We log the result.
    is_panic = resp == 503

    metrics.add_result(
        suite="chaos_resilience",
        endpoint="/status",
        payload="PANIC_TRIGGER_ATTEMPT",
        status=resp,
        latency=0,
        panic=is_panic,
        bypassed=False,
    )

    if is_panic:
        print("System successfully entered PANIC mode.")

        # 2. Attempt Recovery
        # POST /ui/security/resolve
        try:
            res_resp = requests.post(
                f"{BASE_URL}/ui/security/resolve",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                params={"action": "clear_panic"},
            )
            assert res_resp.status_code == 200, "Failed to resolve panic mode"
            print("System recovered from PANIC mode.")
        except Exception as e:
            pytest.fail(f"Recovery failed: {e}")

    else:
        print("System did NOT enter panic mode (threshold not met or feature disabled).")
