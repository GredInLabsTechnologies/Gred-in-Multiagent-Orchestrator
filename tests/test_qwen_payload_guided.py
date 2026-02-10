import os
import time

import pytest

from tests.llm.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.llm.prompt_templates import SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS
from tests.metrics.runtime_metrics import MetricsCollector


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
    collector.save_report("out/metrics/payload_guided_report.json")


def test_path_traversal_guided(llm, metrics, llm_available, test_client, valid_token):
    """
    Test guided path traversal using LLM generated payloads.
    """
    if not llm_available:
        payloads = [
            "../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "....//....//etc/passwd",
            "%2e%2e/%2e%2e/etc/passwd",
        ]
    else:
        payloads = llm.generate_payloads(SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS["path_traversal"])
    assert len(payloads) > 0, "LLM failed to generate payloads"

    for payload in payloads:
        start_time = time.time()
        try:
            response = test_client.get(
                "/file",
                params={"path": payload},
                headers={"Authorization": f"Bearer {valid_token}"},
            )
            _require_orchestrator_response(
                response, f"path traversal payload {payload[:50]}"
            )
            latency = time.time() - start_time

            # Analyze results
            panic = response.status_code == 503
            # If we get 200/500 and the content looks leaked, it's a bypass
            bypassed = response.status_code == 200 and (
                "root:" in response.text or "[extensions]" in response.text
            )

            metrics.add_result(
                suite="payload_guided",
                endpoint="/file",
                payload=payload,
                status=response.status_code,
                latency=latency,
                panic=panic,
                bypassed=bypassed,
            )

            # Basic sanity: we expect 403 or 503 for malicious payloads
            # If 200, it's a critical failure of the security layer
            assert (
                response.status_code != 200 or not bypassed
            ), f"CRITICAL: Payload {payload} bypassed protection!"

        except UnicodeEncodeError:
            metrics.add_result("payload_guided", "/file", payload, 0, 0, False, False)
            print(f"Skipping payload due to encoding error: {payload}")
            continue


def test_auth_bypass_guided(llm, metrics, llm_available, test_client):
    """
    Test guided authentication bypass.
    """
    if not llm_available:
        payloads = [
            "invalid-token-1234567890",
            "Bearer invalid-token-1234567890",
            "".join(["A" for _ in range(32)]),
            "test-token-00000000000000000000000000000000",
        ]
    else:
        payloads = llm.generate_payloads(SYSTEM_PAYLOAD_GENERATOR, USER_PROMPTS["auth_bypass"])
    assert len(payloads) > 0

    for payload in payloads:
        token = str(payload)
        start_time = time.time()
        try:
            # httpx/Starlette requires header values to be ASCII encodable (and practically printable).
            # Some LLM outputs contain non-ASCII/control chars that are not representable as HTTP headers.
            if (not token.isascii()) or any(ord(c) < 0x20 for c in token):
                metrics.add_result("payload_guided", "/status", token, 0, 0, False, False)
                print(f"Skipping auth payload not valid as HTTP header: {token!r}")
                continue

            response = test_client.get(
                "/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            _require_orchestrator_response(
                response, f"auth bypass payload {token[:50]}"
            )
            latency = time.time() - start_time

            # 200 with a fake token is a bypass
            bypassed = response.status_code == 200

            metrics.add_result(
                suite="payload_guided",
                endpoint="/status",
                payload=token,
                status=response.status_code,
                latency=latency,
                panic=False,
                bypassed=bypassed,
            )

            assert response.status_code in [
                401,
                403,
                503,
            ], f"Security failure: Token {payload} allowed access (Status {response.status_code})"

        except Exception as exc:
            pytest.fail(f"Orchestrator call failed for auth payload {token[:50]}: {exc}")


def _require_orchestrator_response(response, context: str) -> None:
    if response is None:
        pytest.fail(f"Orchestrator call failed (no response) during {context}")
    status_code = getattr(response, "status_code", 0)
    if status_code == 0:
        pytest.fail(f"Orchestrator call failed (status 0) during {context}")
    if status_code >= 500 and status_code != 503:
        pytest.fail(f"Orchestrator error {status_code} during {context}")
