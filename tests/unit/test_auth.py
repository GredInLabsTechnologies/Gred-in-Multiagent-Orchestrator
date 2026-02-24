import os
import pytest
from tools.gimo_server.config import (
    ORCH_ACTIONS_TOKEN,
    ORCH_OPERATOR_TOKEN,
    TOKENS
)
from tools.gimo_server.security.threat_level import ThreatLevel

@pytest.fixture(autouse=True)
def setup_tokens():
    """Ensure test tokens are in the real TOKENS set."""
    TOKENS.add(_admin_token())
    TOKENS.add(ORCH_OPERATOR_TOKEN)
    TOKENS.add(ORCH_ACTIONS_TOKEN)
    TOKENS.add("test-admin-token")
    yield


def _admin_token() -> str:
    return os.environ.get("ORCH_TOKEN", "test-token-admin-1234567890")

def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}

def _operator_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ORCH_OPERATOR_TOKEN}"}

def _actions_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ORCH_ACTIONS_TOKEN}"}

class TestAuthentication:
    """Consolidated authentication validation tests from test_auth_validation.py and test_security_core.py."""

    @pytest.mark.parametrize("header_value", [
        "",
        "Bearer ",
        "Bearer    ",
        "token123456789012345678",
        "basic token123456789012345678",
        "Bearer",
        "BearerToken123456789012345678",
        "Bearer short",
        "Bearer 123456789"
    ])
    def test_invalid_auth_headers_rejected(self, test_client, header_value):
        """Verify various invalid or malformed auth headers are rejected (401)."""
        headers = {"Authorization": header_value} if header_value else {}
        response = test_client.get("/status", headers=headers)
        assert response.status_code == 401
        detail = response.json().get("detail", "").lower()
        assert any(x in detail for x in ["token", "missing", "invalid", "scheme", "session"])

    def test_case_sensitive_token(self, test_client, valid_token):
        """Verify token validation is case-sensitive."""
        if valid_token == valid_token.upper():
            pytest.skip("Token is already uppercase")
        
        response = test_client.get("/status", headers={"Authorization": f"Bearer {valid_token.upper()}"})
        assert response.status_code == 401

    @pytest.mark.parametrize("payload", [
        "token123\x00admin",
        "token123\nX-Admin: true",
        "' OR '1'='1",
        "admin'--",
        "1234567890123456'; DROP TABLE users--"
    ])
    def test_token_injection_rejected(self, test_client, payload):
        """Verify malicious token patterns are rejected (401)."""
        response = test_client.get("/status", headers={"Authorization": f"Bearer {payload}"})
        assert response.status_code == 401

class TestRBAC:
    """Role-Based Access Control tests from test_api_security.py and test_ops_v2.py."""

    @pytest.mark.parametrize("endpoint,method", [
        ("/ops/provider", "get"),
        ("/ops/policy", "get"),
        ("/ui/service/restart", "post"),
        ("/ops/trust/reset", "post"),
        ("/ops/config", "get"), # Actions cannot read config in some versions, check rbac
        ("/ui/audit", "get"),
        ("/ui/allowlist", "get"),
    ])
    def test_actions_role_restricted(self, test_client, endpoint, method):
        """Verify 'actions' role cannot access restricted endpoints (403)."""
        response = getattr(test_client, method)(endpoint, headers=_actions_headers())
        assert response.status_code == 403

    @pytest.mark.parametrize("endpoint,method,json_body", [
        ("/ops/provider", "put", {"active": "openai", "providers": {}}),
        ("/ops/config", "put", {"default_auto_run": True, "draft_cleanup_ttl_days": 7}),
        ("/ops/trust/reset", "post", None),
        ("/ops/plan", "put", {
            "id": "p1", "title": "test", "workspace": ".", "created": "2024-01-01",
            "objective": "test", "tasks": []
        }),
    ])
    def test_operator_role_restricted_mutations(self, test_client, endpoint, method, json_body):
        """Verify 'operator' role cannot perform admin-only mutations (403)."""
        kwargs = {"headers": _operator_headers()}
        if json_body:
            kwargs["json"] = json_body
        response = getattr(test_client, method)(endpoint, **kwargs)
        assert response.status_code == 403

    def test_operator_allowed_ops(self, test_client):
        """Verify 'operator' can perform allowed operations."""
        # Can read config
        response = test_client.get("/ops/config", headers=_operator_headers())
        assert response.status_code == 200
        
        # Can list connectors
        response = test_client.get("/ops/connectors", headers=_operator_headers())
        assert response.status_code == 200

    def test_admin_role_full_access(self, test_client):
        """Verify admin role has full access."""
        endpoints = ["/ops/config", "/status", "/ops/provider", "/ui/repos"]
        for ep in endpoints:
            response = test_client.get(ep, headers=_admin_headers())
            assert response.status_code in (200, 404)

class TestThreatResponse:
    """Tests for ThreatEngine integration and Lockdown behavior."""

    def test_lockdown_blocks_unauthenticated(self, test_client):
        """Verify threat engine LOCKDOWN blocks unauthenticated requests (503)."""
        from tools.gimo_server.security import threat_engine
        
        old_level = threat_engine.level
        threat_engine.level = ThreatLevel.LOCKDOWN
        try:
            # Unauthenticated should be blocked
            response = test_client.get("/status")
            assert response.status_code == 503
            assert "LOCKDOWN" in response.text
            
            # Authenticated admin should still work
            response = test_client.get("/status", headers=_admin_headers())
            assert response.status_code == 200
        finally:
            threat_engine.level = old_level

    def test_auth_failure_escalation_logic(self, test_client):
        """Verify engine escalates threat level on multiple failures from non-whitelisted source."""
        from tools.gimo_server.security import threat_engine
        
        threat_engine.clear_all()
        assert threat_engine.level == ThreatLevel.NOMINAL
        
        # TestClient "testclient" is whitelisted, so we test engine directly
        for _ in range(3):
            threat_engine.record_auth_failure(source="1.2.3.4", detail="bruteforce")
            
        assert threat_engine.level == ThreatLevel.ALERT

    def test_resolution_clears_lockdown(self, test_client):
        """Verify resolution endpoint clears threat level."""
        from tools.gimo_server.security import threat_engine
        threat_engine.level = ThreatLevel.LOCKDOWN
        
        response = test_client.post(
            "/ui/security/resolve?action=clear_all",
            headers=_admin_headers()
        )
        assert response.status_code == 200
        assert threat_engine.level == ThreatLevel.NOMINAL
