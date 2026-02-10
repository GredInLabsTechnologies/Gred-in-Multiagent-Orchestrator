"""
Exhaustive Adversarial Security Test Suite
==========================================
Requires:
1. LM Studio running on localhost:1234 with Qwen 3 8B (or compatible)
2. Orchestrator server running on localhost:9325 (optional, can use TestClient)

Run with: pytest tests/adversarial/ -v --tb=short
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.adversarial.prompts_exhaustive import ATTACK_VECTORS, SYSTEM_ADVERSARIAL_MASTER
from tests.llm.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.metrics.runtime_metrics import MetricsCollector

# This suite requires an external LLM server and is considered integration-level.
pytestmark = pytest.mark.integration

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234/v1")
# Generated metrics go to out/ by default (gitignored). Golden snapshots (if any)
# should live under tests/metrics/golden/.
REPORT_DIR = Path(__file__).parent.parent.parent / "out" / "metrics"


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def llm():
    """LM Studio client fixture."""
    return LMStudioClient(host=LM_STUDIO_HOST)


@pytest.fixture(scope="module")
def llm_available():
    """Check if LM Studio is available."""
    available = is_lm_studio_available(LM_STUDIO_HOST)
    if not available:
        if os.environ.get("LM_STUDIO_REQUIRED", "0").strip() in {"1", "true", "yes"}:
            pytest.fail(
                "LM Studio/OpenAI-compatible LLM not available but LM_STUDIO_REQUIRED=1"
            )
        pytest.skip("LM Studio not available - these tests require a running LLM")
    return available


@pytest.fixture(scope="module")
def metrics():
    """Metrics collector for the test run."""
    collector = MetricsCollector()
    yield collector
    # Save comprehensive report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"adversarial_exhaustive_{timestamp}.json"
    collector.save_report(str(report_path))

    # Also save a summary
    summary = {
        "timestamp": timestamp,
        "total_tests": len(collector.results),
        "bypasses": sum(1 for r in collector.results if getattr(r, "bypassed", False)),
        "panics": sum(1 for r in collector.results if getattr(r, "panic_triggered", False)),
        "categories_tested": list(set(getattr(r, "suite", "unknown") for r in collector.results)),
    }
    summary_path = REPORT_DIR / "adversarial_summary_latest.json"
    summary_path.write_text(json.dumps(summary, indent=2))


# ═══════════════════════════════════════════════════════════════════════════
# PATH TRAVERSAL TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestPathTraversalExhaustive:
    """Exhaustive path traversal testing with LLM-generated payloads."""

    @pytest.mark.parametrize(
        "vector_name",
        [
            "path_traversal_basic",
            "path_traversal_encoded",
            "path_traversal_null_byte",
            "path_traversal_windows",
            "path_traversal_filter_bypass",
            "path_traversal_combo",
        ],
    )
    def test_path_traversal_vectors(
        self, vector_name, llm, llm_available, metrics, test_client, valid_token
    ):
        """Test path traversal with LLM-generated payloads."""
        prompt = ATTACK_VECTORS[vector_name]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)

        assert len(payloads) > 0, f"LLM failed to generate payloads for {vector_name}"

        for payload in payloads:
            result = self._test_single_payload(
                payload, vector_name, test_client, valid_token, metrics
            )

            # CRITICAL: No bypass should ever succeed
            assert not result[
                "bypassed"
            ], f"CRITICAL SECURITY FAILURE: {vector_name} bypassed with: {payload}"

    def _test_single_payload(
        self, payload: str, category: str, client, token: str, metrics
    ) -> dict[str, Any]:
        """Test a single payload and record metrics."""
        start = time.time()

        try:
            response = client.get(
                "/file",
                params={"path": payload},
                headers={"Authorization": f"Bearer {token}"},
            )
            _require_orchestrator_response(
                response, f"path traversal payload {category}: {payload[:50]}"
            )
            latency = time.time() - start

            # Detect bypass: 200 with sensitive content
            bypassed = response.status_code == 200 and any(
                marker in response.text.lower()
                for marker in ["root:", "[extensions]", "sam", "system32", "passwd"]
            )

            panic = response.status_code == 503

            result = {
                "suite": category,
                "endpoint": "/file",
                "payload": payload[:200],  # Truncate for logging
                "status": response.status_code,
                "latency": latency,
                "panic": panic,
                "bypassed": bypassed,
            }

            metrics.add_result(**result)
            return result

        except Exception as e:
            pytest.fail(
                f"Orchestrator call failed for {category} payload {payload[:50]}: {e}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# AUTHENTICATION BYPASS TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestAuthBypassExhaustive:
    """Exhaustive authentication bypass testing."""

    @pytest.mark.parametrize(
        "vector_name",
        [
            "auth_empty_variations",
            "auth_length_boundary",
            "auth_format_attacks",
            "auth_encoding_attacks",
            "auth_timing_attacks",
            "auth_parser_smuggling",
        ],
    )
    def test_auth_bypass_vectors(self, vector_name, llm, llm_available, metrics, test_client):
        """Test auth bypass with LLM-generated tokens."""
        prompt = ATTACK_VECTORS[vector_name]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)

        assert len(payloads) > 0, f"LLM failed to generate payloads for {vector_name}"

        for payload in payloads:
            result = self._test_auth_payload(payload, vector_name, test_client, metrics)

            # Any 200 response with invalid token is a bypass
            assert not result[
                "bypassed"
            ], f"CRITICAL: Auth bypass with {vector_name}: {payload[:50]}..."

    def _test_auth_payload(self, token: str, category: str, client, metrics) -> dict[str, Any]:
        """Test a single auth token."""
        start = time.time()

        safe_token = _ascii_safe_token(token)

        try:
            response = client.get(
                "/status",
                headers={"Authorization": f"Bearer {safe_token}"},
            )
            _require_orchestrator_response(
                response, f"auth bypass payload {category}: {token[:50]}"
            )
            latency = time.time() - start

            # 200 with invalid token = bypass
            bypassed = response.status_code == 200

            result = {
                "suite": category,
                "endpoint": "/status",
                "payload": token[:100] if len(token) > 100 else token,
                "status": response.status_code,
                "latency": latency,
                "panic": response.status_code == 503,
                "bypassed": bypassed,
            }

            metrics.add_result(**result)
            return result

        except Exception as e:
            pytest.fail(
                f"Orchestrator call failed for {category} token {token[:50]}: {e}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# INJECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestInjectionExhaustive:
    """Exhaustive injection testing."""

    @pytest.mark.parametrize(
        "vector_name",
        [
            "injection_command",
            "injection_sql",
            "injection_ldap",
            "injection_xpath",
            "injection_ssti",
            "injection_windows_shell",
        ],
    )
    def test_injection_vectors(
        self, vector_name, llm, llm_available, metrics, test_client, valid_token
    ):
        """Test injection attacks with LLM-generated payloads."""
        prompt = ATTACK_VECTORS[vector_name]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)

        assert len(payloads) > 0, f"LLM failed to generate payloads for {vector_name}"

        for payload in payloads:
            start = time.time()

            try:
                response = test_client.get(
                    "/file",
                    params={"path": payload},
                    headers={"Authorization": f"Bearer {valid_token}"},
                )
                _require_orchestrator_response(
                    response, f"injection payload {vector_name}: {payload[:50]}"
                )
                latency = time.time() - start

                # Detect successful injection by looking for command output
                bypassed = response.status_code == 200 and any(
                    marker in response.text.lower()
                    for marker in [
                        "uid=",
                        "gid=",  # Unix command output
                        "volume serial",  # Windows dir output
                        "syntax error",  # SQL error
                        "49",  # 7*7 result (SSTI)
                    ]
                )

                metrics.add_result(
                    suite=vector_name,
                    endpoint="/file",
                    payload=payload[:200],
                    status=response.status_code,
                    latency=latency,
                    panic=response.status_code == 503,
                    bypassed=bypassed,
                )

                assert not bypassed, f"INJECTION SUCCESS with {vector_name}: {payload}"

            except Exception as exc:
                pytest.fail(
                    f"Orchestrator call failed for injection {vector_name} payload {payload[:50]}: {exc}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# SPECIAL CHARACTER TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestSpecialCharsExhaustive:
    """Test handling of special and unicode characters."""

    @pytest.mark.parametrize(
        "vector_name",
        [
            "special_unicode",
            "special_control_chars",
            "special_path_weirdness",
        ],
    )
    def test_special_char_vectors(
        self, vector_name, llm, llm_available, metrics, test_client, valid_token
    ):
        """Test special character handling."""
        prompt = ATTACK_VECTORS[vector_name]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)
        assert len(payloads) > 0, f"LLM failed to generate payloads for {vector_name}"

        for payload in payloads:
            try:
                response = test_client.get(
                    "/file",
                    params={"path": payload},
                    headers={"Authorization": f"Bearer {valid_token}"},
                )
                _require_orchestrator_response(
                    response, f"special chars payload {vector_name}: {repr(payload)[:50]}"
                )

                # Should get 400, 403, or 503 - not 200 or 500
                assert response.status_code in [
                    400,
                    403,
                    404,
                    503,
                ], f"Unexpected response {response.status_code} for special char payload"

                metrics.add_result(
                    suite=vector_name,
                    endpoint="/file",
                    payload=repr(payload)[:100],
                    status=response.status_code,
                    latency=0,
                    panic=response.status_code == 503,
                    bypassed=False,
                )

            except UnicodeEncodeError:
                # Expected for some payloads
                continue


# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMIT BYPASS TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestRateLimitBypass:
    """Verify that IP-based rate limiting cannot be bypassed via header spoofing."""

    def test_ratelimit_header_spoofing(
        self, llm, llm_available, metrics, test_client, valid_token
    ):
        """Exhaust the rate limit, then confirm spoofed headers do not reset the counter."""
        # Phase 1: exhaust rate limit (limit is 100 req/min; request #101 triggers 429)
        for _ in range(102):
            resp = test_client.get(
                "/status", headers={"Authorization": f"Bearer {valid_token}"}
            )
            _require_orchestrator_response(resp, "rate limit warmup")
            if resp.status_code == 429:
                break

        baseline = test_client.get(
            "/status", headers={"Authorization": f"Bearer {valid_token}"}
        )
        _require_orchestrator_response(baseline, "rate limit baseline")
        assert baseline.status_code == 429, "Rate limit not triggered - precondition failed"

        # Phase 2: Qwen generates IP-spoofing header payloads
        prompt = ATTACK_VECTORS["ratelimit_header_spoofing"]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)
        assert len(payloads) > 0, "LLM failed to generate rate limit bypass payloads"

        for payload in payloads:
            headers = {"Authorization": f"Bearer {valid_token}"}
            # Payload may be "Header-Name: value" or a bare IP
            if ":" in payload and not payload.strip().startswith("http"):
                key, val = payload.split(":", 1)
                headers[key.strip()] = val.strip()
            else:
                headers["X-Forwarded-For"] = payload.strip()

            response = test_client.get("/status", headers=headers)
            _require_orchestrator_response(
                response, f"rate limit spoofing payload {payload[:50]}"
            )
            bypassed = response.status_code == 200

            metrics.add_result(
                suite="ratelimit_header_spoofing",
                endpoint="/status",
                payload=payload[:100],
                status=response.status_code,
                latency=0,
                panic=response.status_code == 503,
                bypassed=bypassed,
            )

            assert not bypassed, f"RATE LIMIT BYPASS via header spoofing: {payload}"


# ═══════════════════════════════════════════════════════════════════════════
# PANIC MODE EVASION TESTS
# ═══════════════════════════════════════════════════════════════════════════
class TestPanicEvasion:
    """Verify that panic-mode lockdown cannot be evaded by attacker techniques."""

    def test_panic_evasion_vectors(
        self, llm, llm_available, metrics, test_client, valid_token
    ):
        """Trigger panic, validate fail-closed semantics, then test Qwen evasion payloads."""
        # Phase 1: trigger panic (threshold = 5 invalid tokens >= 16 chars)
        for i in range(6):
            resp = test_client.get(
                "/status",
                headers={"Authorization": f"Bearer adversarial-panic-trigger-{i:020d}"},
            )
            _require_orchestrator_response(resp, "panic trigger")

        # Verify panic is active (invalid token → 503 from middleware)
        baseline = test_client.get(
            "/status",
            headers={"Authorization": "Bearer not-a-real-token-panic-check-active"},  # NOSONAR S8217
        )
        _require_orchestrator_response(baseline, "panic baseline")
        assert baseline.status_code == 503, "Panic mode not triggered - precondition failed"

        # Verify valid token still works (fail-closed blocks attackers, not operators)
        legit = test_client.get(
            "/status", headers={"Authorization": f"Bearer {valid_token}"}
        )
        _require_orchestrator_response(legit, "panic legit token")
        assert legit.status_code == 200, "Valid token blocked during panic - misconfigured"

        # Phase 2: Qwen generates evasion attempts
        prompt = ATTACK_VECTORS["panic_evasion"]
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, prompt)
        assert len(payloads) > 0, "LLM failed to generate panic evasion payloads"

        for payload in payloads:
            response = test_client.get(
                "/status", headers={"Authorization": f"Bearer {payload}"}
            )
            _require_orchestrator_response(
                response, f"panic evasion payload {payload[:50]}"
            )
            bypassed = response.status_code == 200

            metrics.add_result(
                suite="panic_evasion",
                endpoint="/status",
                payload=payload[:100],
                status=response.status_code,
                latency=0,
                panic=response.status_code == 503,
                bypassed=bypassed,
            )

            assert not bypassed, f"PANIC MODE EVADED: {payload}"


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY TEST
# ═══════════════════════════════════════════════════════════════════════════
def test_final_security_summary(metrics):
    """Generate final security summary after all tests."""
    bypasses = [r for r in metrics.results if getattr(r, "bypassed", False)]
    panics = [r for r in metrics.results if getattr(r, "panic_triggered", False)]

    print("\n" + "=" * 60)
    print("ADVERSARIAL SECURITY TEST SUMMARY")
    print("=" * 60)
    print(f"Total payloads tested: {len(metrics.results)}")
    print(f"Bypasses detected: {len(bypasses)}")
    print(f"Panic triggers: {len(panics)}")
    print("=" * 60)

    if bypasses:
        print("\n⚠️  CRITICAL: BYPASSES DETECTED!")
        for b in bypasses[:10]:  # Show first 10
            print(f"  - {b.suite}: {b.payload[:50]}...")
    else:
        print("\n✅ NO BYPASSES DETECTED - Security validated")

    # This should pass only if no bypasses
    assert len(bypasses) == 0, f"SECURITY FAILURE: {len(bypasses)} bypasses detected"


def _require_orchestrator_response(response, context: str) -> None:
    if response is None:
        pytest.fail(f"Orchestrator call failed (no response) during {context}")
    status_code = getattr(response, "status_code", 0)
    if status_code == 0:
        pytest.fail(f"Orchestrator call failed (status 0) during {context}")
    if status_code >= 500 and status_code != 503:
        pytest.fail(f"Orchestrator error {status_code} during {context}")


def _ascii_safe_token(token: str) -> str:
    try:
        token.encode("ascii")
        return token
    except UnicodeEncodeError:
        return token.encode("utf-8", errors="ignore").decode("ascii", errors="ignore")
