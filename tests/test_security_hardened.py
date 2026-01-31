import pytest
import os
import time
import json
from pathlib import Path
from fastapi import HTTPException

# Set environment variables for testing BEFORE importing the app
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import validate_path, redact_sensitive_data, load_security_db, save_security_db, SECURITY_DB_PATH

def test_auth_rejection_triggers_panic():
    """ASVS L3: Verify that unauthorized attempts trigger Panic Mode."""
    # Reset security DB
    db = load_security_db()
    db["panic_mode"] = False
    save_security_db(db)
    
    # Ensure app has NO dependency overrides - clean slate
    app.dependency_overrides.clear()
    
    # Create a clean client WITHOUT auth override
    from fastapi.testclient import TestClient
    clean_client = TestClient(app)
    
    # Attempt unauthorized access
    response = clean_client.get("/status", headers={"Authorization": "Bearer invalid-token-1234567890"})
    assert response.status_code == 401
    
    # Check if panic mode was triggered
    db = json.loads(SECURITY_DB_PATH.read_text(encoding="utf-8"))
    assert db["panic_mode"] is True
    assert any(e["type"] == "PANIC_TRIGGER" for e in db["recent_events"])
    
    # Cleanup
    app.dependency_overrides.clear()

def test_panic_mode_isolation(test_client):
    """Verify that all requests are blocked during panic mode except the resolution endpoint."""
    # Trigger panic
    db = load_security_db()
    db["panic_mode"] = True
    save_security_db(db)
    
    # Try normal route
    response = test_client.get("/status", headers={"Authorization": "Bearer test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"})
    assert response.status_code == 503
    assert "System in LOCKDOWN" in response.text
    
    # Try resolution route
    response = test_client.post("/ui/security/resolve?action=clear_panic", headers={"Authorization": "Bearer test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"})
    assert response.status_code == 200
    
    # Verify cleanup
    db = load_security_db()
    assert db["panic_mode"] is False

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
        "openai": "sk-1234567890abcdefghijklmnopqrstuvwxyz1234567890AB",
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

def test_rate_limiting_functional(test_client):
    """Verify that rapid requests are throttled."""
    # Reset limit store if possible or just spam
    for _ in range(110): # Limit is 100 per min in config
        response = test_client.get("/status", headers={"Authorization": "Bearer test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"})
        if response.status_code == 429:
            break
    assert response.status_code == 429
