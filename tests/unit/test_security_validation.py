import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from tools.gimo_server.security.validation import (
    _normalize_path,
    get_active_repo_dir,
    get_allowed_paths,
    load_repo_registry,
    save_repo_registry,
    serialize_allowlist,
    validate_path,
)


def test_load_repo_registry_missing(tmp_path):
    path = tmp_path / "registry.json"
    with patch("tools.gimo_server.security.validation.REPO_REGISTRY_PATH", path):
        data = load_repo_registry()
        assert data == {"active_repo": None, "repos": []}


def test_save_repo_registry(tmp_path):
    path = tmp_path / "registry.json"
    with patch("tools.gimo_server.security.validation.REPO_REGISTRY_PATH", path):
        save_repo_registry({"test": True})
        assert json.loads(path.read_text()) == {"test": True}


def test_get_active_repo_dir_fallback(tmp_path):
    # Case: No registry file
    with patch("tools.gimo_server.security.validation.REPO_REGISTRY_PATH", tmp_path / "none"):
        assert get_active_repo_dir() == Path.cwd()


def test_get_active_repo_dir_exists(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"active_repo": str(active)}))
    with patch("tools.gimo_server.security.validation.REPO_REGISTRY_PATH", path):
        assert get_active_repo_dir() == active.resolve()


def test_normalize_path_null_byte():
    assert _normalize_path("file\0.txt", Path(".")) is None


def test_normalize_path_reserved():
    assert _normalize_path("CON", Path(".")) is None
    assert _normalize_path("LPT1.txt", Path(".")) is None


def test_normalize_path_absolute_outside(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    assert _normalize_path(str(outside), base) is None


def test_normalize_path_valid(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    valid = base / "valid.py"
    valid.write_text("content")
    assert _normalize_path("valid.py", base) == valid.resolve()


def test_normalize_path_exception():
    # Trigger exception via invalid input type or similar
    assert _normalize_path(None, Path(".")) is None


def test_validate_path_success(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    valid = base / "valid.py"
    valid.write_text("ok")
    assert validate_path("valid.py", base) == valid.resolve()


def test_validate_path_denied():
    with pytest.raises(HTTPException) as exc:
        validate_path("../outside", Path("."))
    assert exc.value.status_code == 403


def test_get_allowed_paths_none():
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", Path("nonexistent")):
        assert get_allowed_paths(Path(".")) == set()


def test_get_allowed_paths_success(tmp_path):
    path = tmp_path / "allowed.json"
    data = {"timestamp": time.time(), "paths": ["test.py"]}
    path.write_text(json.dumps(data))
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", path):
        with patch("tools.gimo_server.security.validation.ALLOWLIST_TTL_SECONDS", 100):
            paths = get_allowed_paths(tmp_path)
            assert str(tmp_path / "test.py") in [str(p) for p in paths]


def test_get_allowed_paths_new_format_success(tmp_path):
    allowlist_path = tmp_path / "allowed.json"
    data = {
        "paths": [
            {"path": "test.py", "expires_at": "2099-01-01T00:00:00Z"},
        ]
    }
    allowlist_path.write_text(json.dumps(data))
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", allowlist_path):
        paths = get_allowed_paths(tmp_path)
        assert str(tmp_path / "test.py") in [str(p) for p in paths]


def test_get_allowed_paths_new_format_expired(tmp_path):
    allowlist_path = tmp_path / "allowed.json"
    data = {
        "paths": [
            {"path": "test.py", "expires_at": "2000-01-01T00:00:00Z"},
        ]
    }
    allowlist_path.write_text(json.dumps(data))
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", allowlist_path):
        assert get_allowed_paths(tmp_path) == set()


def test_get_allowed_paths_new_format_missing_expires_is_denied(tmp_path):
    allowlist_path = tmp_path / "allowed.json"
    data = {
        "paths": [
            {"path": "test.py"},
        ]
    }
    allowlist_path.write_text(json.dumps(data))
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", allowlist_path):
        assert get_allowed_paths(tmp_path) == set()


def test_get_allowed_paths_expired(tmp_path):
    path = tmp_path / "allowed.json"
    data = {"timestamp": time.time() - 1000, "paths": ["test.py"]}
    path.write_text(json.dumps(data))
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", path):
        with patch("tools.gimo_server.security.validation.ALLOWLIST_TTL_SECONDS", 100):
            assert get_allowed_paths(tmp_path) == set()


def test_get_allowed_paths_error(tmp_path):
    path = tmp_path / "allowed.json"
    path.write_text("corrupt json")
    with patch("tools.gimo_server.security.validation.ALLOWLIST_PATH", path):
        assert get_allowed_paths(tmp_path) == set()


def test_serialize_allowlist(tmp_path):
    (tmp_path / "file.py").write_text("py")
    (tmp_path / "subdir").mkdir()

    paths = {tmp_path / "file.py", tmp_path / "subdir", tmp_path / "nonexistent"}
    result = serialize_allowlist(paths)

    assert any(r["path"] == str(tmp_path / "file.py") and r["type"] == "file" for r in result)
    assert any(r["path"] == str(tmp_path / "subdir") and r["type"] == "dir" for r in result)

    # Test exception in loop
    with patch("pathlib.Path.is_file", side_effect=Exception("error")):
        assert serialize_allowlist({tmp_path / "file.py"}) == []
