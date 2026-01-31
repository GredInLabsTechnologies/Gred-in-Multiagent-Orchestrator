import pytest
import requests
import time
import json
from tests.llm.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.llm.prompt_templates import SYSTEM_ADAPTIVE_ATTACKER
from tests.metrics.runtime_metrics import MetricsCollector

# Configuration
BASE_URL = "http://localhost:9325"
AUTH_TOKEN = "CHAOS_MONKEY_TOKEN_2026"

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

def test_adaptive_path_traversal(llm, metrics, llm_available):
    """
    Simulates an attacker learning from failures to bypass file validation.
    """
    history = []
    current_payload = "../etc/passwd"  # Starting point
    
    for i in range(5):  # Max 5 iterations
        start_time = time.time()
        try:
            response = requests.get(
                f"{BASE_URL}/file",
                params={"path": current_payload},
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                timeout=5
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
                bypassed=bypassed
            )
            
            if bypassed:
                pytest.fail(f"Bypass achieved at iteration {i} with payload: {current_payload}")
            
            # Add to history for LLM feedback
            feedback = f"Payload: {current_payload} | Status: {response.status_code} | Message: {response.text[:100]}"
            history.append({"role": "user", "content": feedback})
            
            # Get next payload from LLM or fallback sequence
            if llm_available:
                next_payload = llm.get_feedback_adaptation(SYSTEM_ADAPTIVE_ATTACKER, history)
            else:
                fallback_payloads = [
                    "..\\..\\windows\\system32\\config\\sam",
                    "....//....//etc/passwd",
                    "%2e%2e/%2e%2e/etc/passwd",
                    "..%2f..%2fetc%2fpasswd",
                ]
                next_payload = fallback_payloads[i] if i < len(fallback_payloads) else None
            if not next_payload or next_payload == current_payload:
                break # Converged or failed
                
            current_payload = next_payload.strip()
            # Clean up LLM output (sometimes it gives extra text)
            if "\n" in current_payload:
                current_payload = current_payload.split("\n")[0]

        except requests.exceptions.RequestException:
            break
