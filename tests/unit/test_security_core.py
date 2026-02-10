from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from tools.gimo_server.security.audit import audit_log, log_panic, redact_sensitive_data
from tools.gimo_server.security.auth import AuthContext, verify_token
from tools.gimo_server.security.common import get_safe_actor, load_json_db
from tools.gimo_server.security.rate_limit import check_rate_limit, rate_limit_store


# --- Auth tests ---
@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
def test_verify_token_success():
    credentials = MagicMock()
    credentials.credentials = "long-valid-token-123456"
    assert verify_token(MagicMock(), credentials) == AuthContext(
        token="long-valid-token-123456", role="admin"
    )


@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
def test_verify_token_too_short():
    credentials = MagicMock()
    credentials.credentials = "short"
    with pytest.raises(HTTPException) as exc:
        verify_token(MagicMock(), credentials)
    assert exc.value.status_code == 401


@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
def test_verify_token_empty():
    credentials = MagicMock()
    credentials.credentials = ""
    with pytest.raises(HTTPException) as exc:
        verify_token(MagicMock(), credentials)
    assert exc.value.status_code == 401


def test_verify_token_missing():
    with pytest.raises(HTTPException) as exc:
        verify_token(MagicMock(), None)
    assert exc.value.status_code == 401


@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
@patch("tools.gimo_server.security.load_security_db")
@patch("tools.gimo_server.security.save_security_db")
def test_verify_token_invalid_trigger_panic(mock_save, mock_load):
    mock_load.return_value = {"panic_mode": False, "recent_events": []}
    credentials = MagicMock()
    credentials.credentials = "invalid-long-secret-token"

    with pytest.raises(HTTPException):
        verify_token(MagicMock(), credentials)

    # Check panic mode only triggers after threshold reached
    args, _ = mock_save.call_args
    assert args[0]["panic_mode"] is False


@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
@patch("tools.gimo_server.security.load_security_db")
@patch("tools.gimo_server.security.save_security_db")
def test_verify_token_invalid_trigger_panic_no_events(mock_save, mock_load):
    # Case: recent_events missing in DB
    mock_load.return_value = {"panic_mode": False}  # missing recent_events
    credentials = MagicMock()
    credentials.credentials = "invalid-long-secret-token"

    with pytest.raises(HTTPException):
        verify_token(MagicMock(), credentials)

    args, _ = mock_save.call_args
    assert args[0]["panic_mode"] is False
    assert "recent_events" in args[0]


@patch("tools.gimo_server.security.auth.ORCH_ACTIONS_TOKEN", "actions-token-123456")
@patch(
    "tools.gimo_server.security.auth.TOKENS",
    {"long-valid-token-123456", "actions-token-123456"},
)
def test_verify_token_actions_role():
    credentials = MagicMock()
    credentials.credentials = "actions-token-123456"
    assert verify_token(MagicMock(), credentials) == AuthContext(
        token="actions-token-123456", role="actions"
    )


# --- Rate Limit tests ---
def test_rate_limit():
    rate_limit_store.clear()
    request = MagicMock()
    request.client.host = "1.2.3.4"

    # First request
    check_rate_limit(request)
    assert rate_limit_store["1.2.3.4"]["count"] == 1

    # Test cleanup
    from tools.gimo_server.security import rate_limit

    # Force cleanup to run by changing last cleanup time
    rate_limit._last_cleanup = datetime.now() - timedelta(seconds=1000)
    rate_limit_store["9.9.9.9"] = {
        "count": 1,
        "start_time": datetime.now() - timedelta(seconds=1000),
    }

    check_rate_limit(request)  # This calls cleanup
    assert "9.9.9.9" not in rate_limit_store

    # Trigger limit
    rate_limit_store["1.2.3.4"]["count"] = 1000
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(request)
    assert exc.value.status_code == 429

    # Test reuse after expiration (window is 60s)
    rate_limit_store["1.2.3.4"] = {
        "count": 10,
        "start_time": datetime.now() - timedelta(seconds=100),
    }
    check_rate_limit(request)
    assert rate_limit_store["1.2.3.4"]["count"] == 1


def test_check_rate_limit_no_client():
    request = MagicMock()
    request.client = None
    check_rate_limit(request)  # Should return None


# --- Audit tests ---
def test_audit_log():
    with patch("tools.gimo_server.security.audit.logging") as mock_logging:
        audit_log("file.py", "1-2", "abc", actor="user")
        mock_logging.info.assert_called_once()
        assert "ACTOR:user" in mock_logging.info.call_args[0][0]


def test_redact_sensitive_data():
    assert redact_sensitive_data("ghp_12345678901234567890123456789012") == "[REDACTED]"
    assert redact_sensitive_data("my password is plain") == "my password is plain"


def test_log_panic(tmp_path):
    with patch("tools.gimo_server.security.audit.logging") as mock_logging:
        log_panic("id-123", "boom", "hash-456", traceback_str="stack")
        assert mock_logging.critical.called
        assert mock_logging.error.called


def test_log_panic_exception():
    with patch(
        "tools.gimo_server.security.audit.logging.getLogger", side_effect=Exception("fail")
    ):
        # Should not crash
        log_panic("id", "reason", "hash")


# --- Common tests ---
def test_get_safe_actor():
    assert get_safe_actor(None) == "unknown"
    assert get_safe_actor("short") == "short"
    assert get_safe_actor("very-long-token-that-should-be-truncated") == "very-lon...ated"


def test_load_json_db_exists(tmp_path):
    path = tmp_path / "db.json"
    path.write_text('{"key": "val"}')
    assert load_json_db(path, dict) == {"key": "val"}


def test_load_json_db_factory():
    # Test factory called on missing file
    factory = MagicMock(return_value={"default": True})
    assert load_json_db(Path("nonexistent"), factory) == {"default": True}
    factory.assert_called_once()


def test_load_json_db_corrupt(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("invalid json")
    factory = MagicMock(return_value={"recovered": True})
    assert load_json_db(path, factory) == {"recovered": True}
    factory.assert_called_once()


def test_save_security_db(tmp_path):
    import json

    db_path = tmp_path / "test_sec.json"
    with patch("tools.gimo_server.security.SECURITY_DB_PATH", db_path):
        from tools.gimo_server.security import save_security_db

        save_security_db({"test": 1})
        assert db_path.exists()
        assert json.loads(db_path.read_text())["test"] == 1
