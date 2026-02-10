"""
Test suite exhaustivo para validación de autenticación.
Diseñado para detectar y prevenir bypasses de autenticación.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set environment variables for testing BEFORE importing the app
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.gimo_server.main import app
from tools.gimo_server.security import load_security_db, save_security_db


class TestAuthenticationBypass:
    """Tests para prevenir bypasses de autenticación."""

    def setup_method(self):
        """Reset security DB and create clean client."""
        db = load_security_db()
        db["panic_mode"] = False
        db["recent_events"] = []
        save_security_db(db)

        # Create client WITHOUT auth override
        app.dependency_overrides.clear()
        import time

        app.state.start_time = time.time()
        self.client = TestClient(app)

    def teardown_method(self):
        """Cleanup after each test."""
        app.dependency_overrides.clear()
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

    def test_empty_token_rejected(self):
        """CRITICAL: Verify empty token is rejected."""
        response = self.client.get("/status", headers={"Authorization": "Bearer "})
        assert response.status_code == 401
        assert (
            "Invalid token" in response.json()["detail"]
            or "Token missing" in response.json()["detail"]
        )

    def test_whitespace_only_token_rejected(self):
        """Verify token with only whitespace is rejected."""
        response = self.client.get("/status", headers={"Authorization": "Bearer    "})
        assert response.status_code == 401
        assert "Invalid token" in response.json()["detail"]

    def test_short_token_rejected(self):
        """Verify tokens shorter than minimum length are rejected."""
        short_tokens = ["a", "ab", "abc", "short", "123456789"]
        for token in short_tokens:
            response = self.client.get("/status", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 401, f"Short token '{token}' should be rejected"
            assert "Invalid token" in response.json()["detail"]

    def test_missing_authorization_header(self):
        """Verify requests without Authorization header are rejected."""
        response = self.client.get("/status")
        assert response.status_code == 401
        assert "Token missing" in response.json()["detail"]

    def test_invalid_token_triggers_panic(self):
        """Verify invalid tokens trigger panic mode."""
        response = None
        for _ in range(5):
            response = self.client.get(
                "/status", headers={"Authorization": "Bearer invalid-token-1234567890"}
            )
            assert response.status_code == 401

        # Verify panic mode was triggered
        db = load_security_db()
        assert db["panic_mode"] is True
        assert any(e["type"] == "PANIC_TRIGGER" for e in db["recent_events"])

    def test_malformed_bearer_scheme(self):
        """Verify malformed Authorization schemes are rejected."""
        malformed_headers = [
            "basic token123456789012345678",  # Wrong scheme
            "token123456789012345678",  # No scheme
            "Bearer",  # No token
            "BearerToken123456789012345678",  # No space
        ]
        for header in malformed_headers:
            response = self.client.get("/status", headers={"Authorization": header})
            assert response.status_code == 401, f"Malformed header '{header}' should be rejected"

    def test_case_sensitive_token(self):
        """Verify token validation is case-sensitive."""
        from tools.gimo_server.config import TOKENS

        valid_token = list(TOKENS)[0]

        # Try uppercase version
        response = self.client.get(
            "/status", headers={"Authorization": f"Bearer {valid_token.upper()}"}
        )
        if valid_token != valid_token.upper():
            assert response.status_code == 401


class TestEndpointProtection:
    """Verify all endpoints require authentication."""

    def setup_method(self):
        """Create clean client without auth."""
        app.dependency_overrides.clear()
        self.client = TestClient(app)
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

    @pytest.mark.parametrize(
        "endpoint,method",
        [
            ("/status", "get"),
            ("/ui/status", "get"),
            ("/ui/audit", "get"),
            ("/ui/allowlist", "get"),
            ("/ui/repos", "get"),
            ("/ui/repos/active", "get"),
            ("/ui/security/events", "get"),
            ("/ui/service/status", "get"),
            ("/tree", "get"),
        ],
    )
    def test_endpoint_requires_auth(self, endpoint, method):
        """Verify critical endpoints reject unauthenticated requests."""
        response = getattr(self.client, method)(endpoint)
        assert response.status_code == 401, f"{endpoint} should require authentication"

    @pytest.mark.parametrize(
        "endpoint,method",
        [
            ("/ui/repos/open?path=.", "post"),
            ("/ui/repos/select?path=.", "post"),
            ("/ui/service/restart", "post"),
            ("/ui/service/stop", "post"),
        ],
    )
    def test_sensitive_endpoints_require_auth(self, endpoint, method):
        """Verify sensitive operations require authentication."""
        response = getattr(self.client, method)(endpoint)
        assert response.status_code == 401, f"{endpoint} should require authentication"


class TestTokenInjection:
    """Tests para prevenir inyecciones de token."""

    def setup_method(self):
        """Setup clean client."""
        app.dependency_overrides.clear()
        self.client = TestClient(app)
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()

    def test_null_byte_injection(self):
        """Verify null byte injection in token is rejected."""
        response = self.client.get("/status", headers={"Authorization": "Bearer token123\x00admin"})
        assert response.status_code == 401

    def test_newline_injection(self):
        """Verify newline injection in token is rejected."""
        response = self.client.get(
            "/status", headers={"Authorization": "Bearer token123\nX-Admin: true"}
        )
        assert response.status_code == 401

    def test_sql_injection_patterns(self):
        """Verify SQL injection patterns in tokens are rejected."""
        sql_patterns = [
            "' OR '1'='1",
            "admin'--",
            "1234567890123456'; DROP TABLE users--",
        ]
        for pattern in sql_patterns:
            response = self.client.get("/status", headers={"Authorization": f"Bearer {pattern}"})
            assert response.status_code == 401


class TestPanicModeIsolation:
    """Test panic mode lockdown behavior."""

    def setup_method(self):
        """Setup."""
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def teardown_method(self):
        """Cleanup."""
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)
        app.dependency_overrides.clear()

    def test_panic_mode_blocks_all_except_resolution(self, valid_token):
        """Verify panic mode blocks everything except resolution endpoint."""
        # Trigger panic mode
        db = load_security_db()
        db["panic_mode"] = True
        save_security_db(db)

        # Try normal endpoint with invalid token - should be blocked
        response = self.client.get(
            "/status", headers={"Authorization": "Bearer invalid-token-1234567890"}
        )
        assert response.status_code == 503
        assert "LOCKDOWN" in response.text

        # Resolution endpoint should work
        response = self.client.post(
            "/ui/security/resolve?action=clear_panic",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200

        # Verify panic was cleared
        db = load_security_db()
        assert db["panic_mode"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
