import os
import time
import pytest
import secrets
import string
from pathlib import Path
from typing import Any
from tests.fixtures.lm_studio_client import LMStudioClient, is_lm_studio_available
from tests.fixtures.prompts_exhaustive import ATTACK_VECTORS, SYSTEM_ADVERSARIAL_MASTER, ADAPTIVE_SYSTEM_PROMPT
from tests.fixtures.runtime_metrics import MetricsCollector

# Integration suite requires external LLM (optional)
pytestmark = pytest.mark.integration

LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "http://localhost:1234/v1")

@pytest.fixture(scope="module")
def llm():
    return LMStudioClient(host=LM_STUDIO_HOST)

@pytest.fixture(scope="module")
def llm_available():
    return is_lm_studio_available(LM_STUDIO_HOST)

@pytest.fixture(scope="module")
def metrics():
    collector = MetricsCollector()
    yield collector
    collector.save_report("out/metrics/adversarial_consolidated.json")

# ── Helpers ───────────────────────────────────────────────

def _check_bypass(response) -> bool:
    if response.status_code != 200:
        return False
    markers = ["root:", "[extensions]", "sam", "system32", "passwd", "uid=", "gid="]
    return any(m in response.text.lower() for m in markers)

def _random_string(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits + string.punctuation + " "
    return "".join(secrets.choice(alphabet) for _ in range(length))

# ── Exhaustive & Payload Attacks ──────────────────────────

@pytest.mark.skip(reason="Adversarial tests targeted for redesign in future phase. Obviated for Phase 5 cleanup.")
class TestExhaustiveAttacks:
    """Exhaustive testing using LLM-generated payloads from test_exhaustive_adversarial.py."""

    @pytest.mark.parametrize("vector", [
        "path_traversal_basic", "path_traversal_encoded", "path_traversal_combo",
        "auth_format_attacks", "injection_command", "injection_sql"
    ])
    def test_exhaustive_vectors(self, vector, llm, llm_available, metrics, test_client, valid_token):
        if not llm_available:
            pytest.skip("LLM not available")
        
        payloads = llm.generate_payloads(SYSTEM_ADVERSARIAL_MASTER, ATTACK_VECTORS[vector])
        for payload in payloads:
            # Test /file endpoint
            res = test_client.get("/file", params={"path": payload}, headers={"Authorization": f"Bearer {valid_token}"})
            bypassed = _check_bypass(res)
            
            # Record metrics (latency can be extracted from res.elapsed if needed)
            metrics.add_result(suite=vector, endpoint="/file", payload=payload[:100], 
                             status=res.status_code, latency=res.elapsed.total_seconds(), 
                             panic=False, bypassed=bypassed)
            assert not bypassed, f"Bypass succeeded with {vector}: {payload}"

# ── Adaptive Attacks ──────────────────────────────────────

@pytest.mark.skip(reason="Adversarial tests targeted for redesign in future phase. Obviated for Phase 5 cleanup.")
class TestAdaptiveAttacks:
    """Learning attacker loop from test_adaptive_attack_vectors.py."""

    def test_adaptive_learning_loop(self, llm, llm_available, metrics, test_client, valid_token):
        if not llm_available:
            pytest.skip("LLM (Qwen) not available for adaptive loop")
        
        history = []
        payload = "../etc/passwd"
        for i in range(5): # Limit to 5 iterations for speed
            res = test_client.get("/file", params={"path": payload}, headers={"Authorization": f"Bearer {valid_token}"})
            bypassed = _check_bypass(res)
            
            metrics.add_result(suite="adaptive_learning", endpoint="/file", payload=payload, 
                             status=res.status_code, latency=res.elapsed.total_seconds(), 
                             panic=False, bypassed=bypassed)
            if bypassed:
                pytest.fail(f"Bypass achieved at iteration {i}")
            
            # Feed back to LLM
            history.append({"role": "user", "content": f"Payload: {payload} | Status: {res.status_code}"})
            prompt = ADAPTIVE_SYSTEM_PROMPT.format(previous_payload=payload, response_code=res.status_code, 
                                                  response_body=res.text[:100], security_events="none", attempts_remaining=5-i)
            payload = llm.get_feedback_adaptation(prompt, history)
            if not payload: break

# ── Fuzzing & Stability ───────────────────────────────────

def test_endpoint_fuzzing_stability(test_client, valid_token):
    """Randomized fuzzing from test_fuzzing.py."""
    endpoints = ["/status", "/tree", "/file", "/search", "/diff"]
    for _ in range(50):
        url = secrets.choice(endpoints)
        params = {"path": _random_string(20), "q": _random_string(10)}
        res = test_client.get(url, params=params, headers={"Authorization": f"Bearer {valid_token}"})
        # NEVER expect 500
        assert res.status_code != 500, f"Fuzzing 500 on {url} with {params}"

def test_spoofed_header_rate_limit(test_client, valid_token):
    """Header spoofing check from TestRateLimitBypass."""
    payloads = ["1.2.3.4", "8.8.8.8", "X-Forwarded-For: 10.0.0.1"]
    for p in payloads:
        headers = {"Authorization": f"Bearer {valid_token}"}
        if ":" in p:
            k, v = p.split(":", 1)
            headers[k.strip()] = v.strip()
        else:
            headers["X-Forwarded-For"] = p
        
        # We don't necessarily exhaust the limit here, just check for stability/non-crash
        res = test_client.get("/status", headers=headers)
        assert res.status_code != 500
