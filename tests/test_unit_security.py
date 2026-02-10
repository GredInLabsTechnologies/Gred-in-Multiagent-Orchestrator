import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from tools.gimo_server.security.validation import _normalize_path, validate_path


def test_normalize_path_traversal():
    # Use tempfile for secure temporary directory handling
    base_dir = Path(tempfile.gettempdir()) / "test_base"
    base_dir.mkdir(exist_ok=True)
    base_dir = base_dir.resolve()

    # Mocking path traversal
    requested = "../../etc/passwd"
    result = _normalize_path(requested, base_dir)
    assert result is None

    # Cleanup
    base_dir.rmdir()


def test_normalize_path_valid():
    base_dir = Path(".").resolve()
    requested = "tools/gimo_server/main.py"
    result = _normalize_path(requested, base_dir)
    assert result is not None
    assert str(result).endswith("main.py")


def test_validate_path_denied():
    # Use tempfile for secure temporary directory handling
    base_dir = Path(tempfile.gettempdir()) / "test_base_validate"
    base_dir.mkdir(exist_ok=True)
    base_dir = base_dir.resolve()

    with pytest.raises(HTTPException) as exc:
        validate_path("../outside.txt", base_dir)
    assert exc.value.status_code == 403

    # Cleanup
    base_dir.rmdir()


def test_security_redaction():
    from tools.gimo_server.security.audit import redact_sensitive_data

    content = "My key is sk-123456789012345678901234567890123456789012345678"
    redacted = redact_sensitive_data(content)
    assert "[REDACTED]" in redacted
    assert "sk-" not in redacted


if __name__ == "__main__":
    pytest.main([__file__])
