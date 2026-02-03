import os
import time

import pytest
import requests

from tests.llm.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.llm.prompt_templates import SYSTEM_ADAPTIVE_ATTACKER
from tests.metrics.runtime_metrics import MetricsCollector

# Configuration
BASE_URL = os.environ.get("ORCH_BASE_URL", "http://localhost:9325")
AUTH_TOKEN = os.environ.get("ORCH_TEST_TOKEN", "")


@pytest.fixture(scope="module")
def llm():
    return LMStudioClient(host="http://localhost:1234/v1")


@pytest.fixture(scope="module")
def llm_available():
    return is_lm_studio_available("http://localhost:1234/v1")


@pytest.fixture(scope="module")
def metrics():
    collector = MetricsCollector()
    yield collector
    collector.save_report("tests/metrics/adaptive_attack_report.json")


@pytest.mark.integration
def test_adaptive_path_traversal(llm, metrics, llm_available):
    """
    Simulates an attacker learning from failures to bypass file validation.
    """
    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.skip("Orchestrator not reachable")

    history = []
    current_payload = "../etc/passwd"  # Starting point

    for i in range(5):  # Max 5 iterations
        current_payload, should_break = _run_adaptive_iteration(
            i, current_payload, llm, metrics, llm_available, history
        )
        if should_break:
            break


def _run_adaptive_iteration(i, current_payload, llm, metrics, llm_available, history):
    """Run a single iteration of the adaptive attack."""
    start_time = time.time()
    try:
        response = requests.get(
            f"{BASE_URL}/file",
            params={"path": current_payload},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            timeout=5,
        )
        latency = time.time() - start_time

        # Analyze response
        panic = response.status_code == 503
        bypassed = response.status_code == 200 and "root:" in response.text

        metrics.add_result(
            suite="adaptive_attack",
            endpoint="/file",
            payload=current_payload,
            status=response.status_code,
            latency=latency,
            panic=panic,
            bypassed=bypassed,
        )

        if bypassed:
            pytest.fail(f"Bypass achieved at iteration {i} with payload: {current_payload}")

        # Add to history for LLM feedback
        feedback = f"Payload: {current_payload} | Status: {response.status_code} | Message: {response.text[:100]}"
        history.append({"role": "user", "content": feedback})

        # Get next payload
        next_payload = _get_next_payload(i, llm, llm_available, history)

        if not next_payload or next_payload == current_payload:
            return current_payload, True

        current_payload = next_payload.strip()
        if "\n" in current_payload:
            current_payload = current_payload.split("\n")[0]

        return current_payload, False

    except requests.exceptions.RequestException:
        return current_payload, True


def _get_next_payload(i, llm, llm_available, history):
    """Get the next payload from LLM or fallback."""
    if llm_available:
        return llm.get_feedback_adaptation(SYSTEM_ADAPTIVE_ATTACKER, history)

    fallback_payloads = [
        "..\\..\\windows\\system32\\config\\sam",
        "....//....//etc/passwd",
        "%2e%2e/%2e%2e/etc/passwd",
        "..%2f..%2fetc%2fpasswd",
    ]
    return fallback_payloads[i] if i < len(fallback_payloads) else None


def _is_orchestrator_available() -> bool:
    try:
        response = requests.get(f"{BASE_URL}/status", timeout=2)
        return response.status_code in {200, 401}
    except requests.exceptions.RequestException:
        return False
