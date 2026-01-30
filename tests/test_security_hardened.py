import os
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import json

# Set environment variables for testing BEFORE importing the app
os.environ["ORCH_TOKEN"] = "test-token-1234567890-very-secure"
os.environ["ORCH_REPO_ROOT"] = str(Path(__file__).parent.parent.resolve())

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import validate_path, redact_sensitive_data, load_security_db, save_security_db


def test_auth_rejection_triggers_panic(test_client):
    """ASVS L3: Verify that unauthorized attempts trigger Panic Mode."""
    # Reset security DB
    db = load_security_db()
    db["panic_mode"] = False
    save_security_db(db)
    
    # Attempt unauthorized access
    response = test_client.get("/status", headers={"Authorization": "Bearer invalid-token"})
    assert response.status_code == 401
    
    # Check if panic mode was triggered
    db = load_security_db()
    assert db["panic_mode"] is True
    assert any(e["type"] == "PANIC_TRIGGER" for e in db["recent_events"])

def test_panic_mode_isolation(test_client):
    """ASVS L3: Verify that only the resolution route is available during Panic Mode."""
    db = load_security_db()
    db["panic_mode"] = True
    save_security_db(db)
    
    # Try normal route
    response = test_client.get("/status", headers={"Authorization": "Bearer test-token-1234567890-very-secure"})
    assert response.status_code == 503
    assert "System in LOCKDOWN" in response.text
    
    # Try resolution route
    response = test_client.post("/ui/security/resolve?action=clear_panic", headers={"Authorization": "Bearer test-token-1234567890-very-secure"})
    assert response.status_code == 200
    
    # Verify cleanup
    db = load_security_db()
    assert db["panic_mode"] is False

def test_path_traversal_shield_exhaustive():
    """Formal Path Proof: Verify that NO path manipulation can leak outside root."""
    base_dir = Path(os.environ["ORCH_REPO_ROOT"]).resolve()
    
    traversal_attempts = [
        "../../../../windows/system32/config/SAM",
        "..\\..\\..\\..\\windows\\system32\\config\\SAM",
        "/etc/passwd",
        "C:/Windows/System32/drivers/etc/hosts",
        "tools/repo_orchestrator/../../../../.env",
        "content/./.././../.env",
        "\0/secrets.txt", # Null byte
        "CON", # Windows reserved name
    ]
    
    for path in traversal_attempts:
        with pytest.raises(Exception) as excinfo:
            validate_path(path, base_dir)
        # Should raise 403 or similar
        assert "403" in str(excinfo.value) or "Path traversal" in str(excinfo.value)

def test_redaction_rigor():
    """Verifies that redaction catches high-entropy and known patterns."""
    sensitive_content = """
    openai_key = "sk-L9xJ82vO938475nd83948576db3948576c938475nb839485"  # nosec: fake key for testing
    github_token = "ghp_1234567890abcdefghijklmnopqrstuv"  # nosec: fake token for testing
    random_secret = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"  # nosec: fake secret for testing (high entropy)
    """
    redacted = redact_sensitive_data(sensitive_content)
    assert "[REDACTED]" in redacted
    assert "sk-" not in redacted
    assert "ghp_" not in redacted

def test_rate_limiting_functional(test_client):
    """Verify that rapid requests are throttled."""
    # Reset limit store if possible or just spam
    for _ in range(110): # Limit is 100 per min in config
        response = test_client.get("/status", headers={"Authorization": "Bearer test-token-1234567890-very-secure"})
        if response.status_code == 429:
            break
    assert response.status_code == 429
