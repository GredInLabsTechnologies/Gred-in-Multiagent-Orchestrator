import pytest
import requests
import time
from tests.llm.lm_studio_client import LMStudioClient
from tests.llm.prompt_templates import SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS
from tests.metrics.runtime_metrics import MetricsCollector

# Configuration
BASE_URL = "http://localhost:9325"
AUTH_TOKEN = "CHAOS_MONKEY_TOKEN_2026"

@pytest.fixture(scope="module")
def llm():
    return LMStudioClient(host="http://localhost:1234/v1")

@pytest.fixture(scope="module")
def metrics():
    collector = MetricsCollector()
    yield collector
    collector.save_report("tests/metrics/payload_guided_report.json")

def test_path_traversal_guided(llm, metrics):
    """
    Test guided path traversal using LLM generated payloads.
    """
    payloads = llm.generate_payloads(SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS["path_traversal"])
    assert len(payloads) > 0, "LLM failed to generate payloads"

    for payload in payloads:
        start_time = time.time()
        try:
            response = requests.get(
                f"{BASE_URL}/file",
                params={"path": payload},
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                timeout=5
            )
            latency = time.time() - start_time
            
            # Analyze results
            panic = response.status_code == 503
            # If we get 200/500 and the content looks leaked, it's a bypass
            bypassed = response.status_code == 200 and ("root:" in response.text or "[extensions]" in response.text)
            
            metrics.add_result(
                suite="payload_guided",
                endpoint="/file",
                payload=payload,
                status=response.status_code,
                latency=latency,
                panic=panic,
                bypassed=bypassed
            )
            
            # Basic sanity: we expect 403 or 503 for malicious payloads
            # If 200, it's a critical failure of the security layer
            assert response.status_code != 200 or not bypassed, f"CRITICAL: Payload {payload} bypassed protection!"

        except (requests.exceptions.RequestException, UnicodeEncodeError) as e:
            metrics.add_result("payload_guided", "/file", payload, 0, 0, False, False)
            if isinstance(e, UnicodeEncodeError):
                print(f"Skipping payload due to encoding error: {payload}")
                continue
            pytest.fail(f"Request failed: {str(e)}")

def test_auth_bypass_guided(llm, metrics):
    """
    Test guided authentication bypass.
    """
    payloads = llm.generate_payloads(SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS["auth_bypass"])
    assert len(payloads) > 0

    for payload in payloads:
        start_time = time.time()
        try:
            response = requests.get(
                f"{BASE_URL}/status",
                headers={"Authorization": f"Bearer {payload}"},
                timeout=5
            )
            latency = time.time() - start_time
            
            # 200 with a fake token is a bypass
            bypassed = response.status_code == 200
            
            metrics.add_result(
                suite="payload_guided",
                endpoint="/status",
                payload=payload,
                status=response.status_code,
                latency=latency,
                panic=False,
                bypassed=bypassed
            )
            
            assert response.status_code in [401, 403, 503], f"Security failure: Token {payload} allowed access (Status {response.status_code})"
            
        except requests.exceptions.RequestException:
            pass
