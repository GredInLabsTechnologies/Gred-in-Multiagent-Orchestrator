import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

# Set environment variables for testing BEFORE importing the app
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.gimo_server.main import app
from tools.gimo_server.security import (
    SECURITY_DB_PATH,
    load_security_db,
    redact_sensitive_data,
    save_security_db,
    validate_path,
    threat_engine
)

@pytest.fixture(autouse=True)
def disable_whitelist():
    """Disable whitelist only for this module's tests."""
    from tools.gimo_server.security import threat_engine
    import tools.gimo_server.security.threat_level
    
    old_val = tools.gimo_server.security.threat_level.WHITELISTED_SOURCES
    tools.gimo_server.security.threat_level.WHITELISTED_SOURCES = set()
    threat_engine.whitelisted_sources = set()
    
    yield
    
    tools.gimo_server.security.threat_level.WHITELISTED_SOURCES = old_val
    threat_engine.whitelisted_sources = old_val


def test_auth_rejection_triggers_panic():
    """ASVS L3: Verify that unauthorized attempts trigger adaptive security levels."""
    from tools.gimo_server.security import threat_engine, save_security_db
    threat_engine.clear_all()
    save_security_db()

    app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    clean_client = TestClient(app)

    # 1. Attempt 5 unauthorized accesses -> GUARDED
    for _ in range(5):
        clean_client.get(
            "/status", headers={"Authorization": "Bearer invalid-token-1234567890"}
        )
    
    assert threat_engine.level.value >= 1 # ALERT or GUARDED
    
    # 2. Attempt until LOCKDOWN (10 total)
    for _ in range(5):
        clean_client.get(
            "/status", headers={"Authorization": "Bearer invalid-token-10"}
        )

    # Check if lockdown was triggered (threat_level 3)
    db = json.loads(SECURITY_DB_PATH.read_text(encoding="utf-8"))
    assert db["threat_level"] >= 2 # Should be at least GUARDED, usually LOCKDOWN if counts are high
    assert threat_engine.level.value >= 2 

    # Cleanup
    threat_engine.clear_all()
    app.dependency_overrides.clear()


def test_panic_mode_isolation(test_client, valid_token):
    """Verify that all requests are blocked during lockdown except for authenticated users and resolution."""
    from tools.gimo_server.security import threat_engine, ThreatLevel
    
    # Force LOCKDOWN
    threat_engine._set_level(ThreatLevel.LOCKDOWN, "Test forced lockdown")
    save_security_db()

    # 1. Try normal route WITHOUT token (should be 503)
    response = test_client.get("/status")
    assert response.status_code == 503
    assert "LOCKDOWN" in response.text

    # 2. Try normal route with INVALID token (should be 503, as invalid token is same as unauthenticated)
    response = test_client.get(
        "/status",
        headers={"Authorization": "Bearer invalid-token-X"},
    )
    assert response.status_code == 503

    # 3. Try normal route with VALID token (should be 200 - authenticated users are NOT blocked)
    response = test_client.get(
        "/status",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200

    # 4. Try resolution route
    response = test_client.post(
        "/ui/security/resolve?action=clear_all",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200

    # 5. Verify cleanup
    assert threat_engine.level == ThreatLevel.NOMINAL


def test_path_traversal_shield_exhaustive(test_client):
    """Test critical path traversal attempts."""
    base_dir = Path(__file__).parent.parent

    malicious_paths = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "valid/../../etc/passwd",
        "CON",
        "test\x00.txt",
    ]

    for path in malicious_paths:
        with pytest.raises(HTTPException):
            validate_path(path, base_dir)


def test_redaction_rigor(test_client):
    """Ensure sensitive patterns are properly redacted."""
    test_data = {
        "openai": "sk-REDACTED-DUMMY-KEY-FOR-TESTING-PURPOSES-ONLY-123",
        "github_token": "ghp_1234567890abcdefghijklmnopqrstuv",
        "aws": "AKIA1234567890ABCDEF",
        "custom_key": 'api-key: "myapikey123456789012"',
    }

    for name, secret in test_data.items():
        redacted = redact_sensitive_data(secret)
        # Nothing sensitive should remain
        assert "sk-" not in redacted or "[REDACTED]" in redacted
        assert "ghp_" not in redacted or "[REDACTED]" in redacted
        assert "AKIA" not in redacted or "[REDACTED]" in redacted


def test_rate_limiting_functional(test_client, valid_token):
    """Verify that rapid requests are throttled."""
    # Reset limit store if possible or just spam
    for _ in range(110):  # Limit is 100 per min in config
        response = test_client.get(
            "/status",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        if response.status_code == 429:
            break
    assert response.status_code == 429
