import os
import time

import json
import pytest
import requests

from tests.llm.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.adversarial.prompts_exhaustive import ADAPTIVE_SYSTEM_PROMPT
from tests.llm.prompt_templates import SYSTEM_ADAPTIVE_ATTACKER
from tests.metrics.runtime_metrics import MetricsCollector

# Configuration
BASE_URL = os.environ.get("ORCH_BASE_URL", "http://localhost:9325")
AUTH_TOKEN = os.environ.get("ORCH_TEST_TOKEN", "")


@pytest.fixture(scope="module")
def llm():
    host = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234/v1")
    return LMStudioClient(host=host)


@pytest.fixture(scope="module")
def llm_available():
    host = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234/v1")
    available = is_lm_studio_available(host)
    if (not available) and (os.environ.get("LM_STUDIO_REQUIRED", "0").strip() in {"1", "true", "yes"}):
        pytest.fail("LM Studio/OpenAI-compatible LLM not available but LM_STUDIO_REQUIRED=1")
    return available


@pytest.fixture(scope="module")
def metrics():
    collector = MetricsCollector()
    yield collector
    collector.save_report("out/metrics/adaptive_attack_report.json")


@pytest.mark.integration
def test_adaptive_path_traversal(llm, metrics, llm_available):
    """
    Simulates an attacker learning from failures to bypass file validation.
    """
    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.fail("Orchestrator not reachable")

    history = []
    current_payload = "../etc/passwd"  # Starting point

    for i in range(10):  # Max 10 iterations
        current_payload, should_break = _run_adaptive_iteration(
            i,
            current_payload,
            llm,
            metrics,
            llm_available,
            history,
            endpoint="/file",
            payload_param="path",
        )
        if should_break:
            break


@pytest.mark.integration
def test_adaptive_auth_bypass(llm, metrics, llm_available):
    """Adaptive auth bypass attempts against /status."""
    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.fail("Orchestrator not reachable")

    history = []
    current_payload = ""  # Start with empty token

    for i in range(10):
        current_payload, should_break = _run_adaptive_iteration(
            i,
            current_payload,
            llm,
            metrics,
            llm_available,
            history,
            endpoint="/status",
            payload_param=None,
            auth_override=True,
        )
        if should_break:
            break


@pytest.mark.integration
def test_adaptive_injection(llm, metrics, llm_available):
    """Adaptive injection attempts using /file?path= endpoint."""
    if not AUTH_TOKEN:
        pytest.skip("ORCH_TEST_TOKEN not set")
    if not _is_orchestrator_available():
        pytest.fail("Orchestrator not reachable")

    history = []
    current_payload = "..\\..\\windows\\system32\\config\\sam & whoami"

    for i in range(8):
        current_payload, should_break = _run_adaptive_iteration(
            i,
            current_payload,
            llm,
            metrics,
            llm_available,
            history,
            endpoint="/file",
            payload_param="path",
        )
        if should_break:
            break


def _run_adaptive_iteration(
    i,
    current_payload,
    llm,
    metrics,
    llm_available,
    history,
    endpoint: str,
    payload_param: str | None,
    auth_override: bool = False,
):
    """Run a single iteration of the adaptive attack."""
    start_time = time.time()
    try:
        params = {payload_param: current_payload} if payload_param else None
        headers = {
            "Authorization": f"Bearer {current_payload if auth_override else AUTH_TOKEN}"
        }

        response = requests.get(
            f"{BASE_URL}{endpoint}",
            params=params,
            headers=headers,
            timeout=5,
        )
        latency = time.time() - start_time

        # Analyze response
        panic = response.status_code == 503
        bypassed = response.status_code == 200 and any(
            marker in response.text.lower()
            for marker in ["root:", "[extensions]", "sam", "system32", "passwd", "uid="]
        )

        metrics.add_result(
            suite=f"adaptive_{endpoint.strip('/')}",
            endpoint=endpoint,
            payload=current_payload,
            status=response.status_code,
            latency=latency,
            panic=panic,
            bypassed=bypassed,
        )

        if bypassed:
            pytest.fail(f"Bypass achieved at iteration {i} with payload: {current_payload}")

        # Add to history for LLM feedback
        feedback = (
            f"Endpoint: {endpoint} | Payload: {current_payload} | "
            f"Status: {response.status_code} | Message: {response.text[:160]}"
        )
        history.append({"role": "user", "content": feedback})

        # Get next payload
        next_payload = _get_next_payload(
            i, llm, llm_available, history, current_payload, response, endpoint
        )

        if not next_payload or next_payload == current_payload:
            return current_payload, True

        current_payload = next_payload.strip()
        if "\n" in current_payload:
            current_payload = current_payload.split("\n")[0]

        return current_payload, False

    except requests.exceptions.RequestException as exc:
        pytest.fail(f"Orchestrator call failed during adaptive attack: {exc}")


def _get_next_payload(i, llm, llm_available, history, previous_payload, response, endpoint):
    """Get the next payload from LLM or fallback."""
    if llm_available:
        system_prompt = ADAPTIVE_SYSTEM_PROMPT.format(
            previous_payload=previous_payload,
            response_code=response.status_code,
            response_body=response.text[:200],
            security_events="panic" if response.status_code == 503 else "none",
            attempts_remaining=max(0, 9 - i),
        )
        raw = llm.get_feedback_adaptation(system_prompt, history)
        if raw:
            parsed = _extract_adaptive_payload(raw)
            if parsed:
                return parsed
        return raw

    fallback_payloads = [
        "..\\..\\windows\\system32\\config\\sam",
        "....//....//etc/passwd",
        "%2e%2e/%2e%2e/etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "\\\\127.0.0.1\\c$\\Windows\\win.ini",
        "\\\\?\\C:\\Windows\\System32\\config\\SAM",
        "C:/Windows/System32/config/SAM",
        "..%255c..%255cwindows%255csystem32%255cconfig%255csam",
        "..%2f..%2f..%2f..%2fWindows%2fSystem32%2fdrivers%2fetc%2fhosts",
    ]
    return fallback_payloads[i] if i < len(fallback_payloads) else None


def _extract_adaptive_payload(raw: str) -> str | None:
    """Extract new_payload from JSON or raw text."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "new_payload" in data:
            return str(data["new_payload"])
    except Exception:
        return raw.strip() if raw else None
    return raw.strip() if raw else None


def _is_orchestrator_available() -> bool:
    try:
        response = requests.get(f"{BASE_URL}/status", timeout=2)
        if response.status_code in {200, 401}:
            return True
        pytest.fail(f"Orchestrator error {response.status_code} during availability check")
    except requests.exceptions.RequestException:
        return False
