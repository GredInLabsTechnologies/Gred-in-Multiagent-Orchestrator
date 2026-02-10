import os
from pathlib import Path
from unittest.mock import patch

from tools.gimo_server.config import _load_or_create_token


def test_token_creation(tmp_path):
    token_file = tmp_path / ".token"
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            if token_file.exists():
                token_file.unlink()
            token = _load_or_create_token()
            assert len(token) > 20
            assert token_file.exists()
            assert token_file.read_text() == token


def test_token_from_env():
    with patch.dict(os.environ, {"ORCH_TOKEN": "env-token"}):
        token = _load_or_create_token()
        assert token == "env-token"


def test_token_from_file(tmp_path):
    token_file = tmp_path / ".token"
    token_file.write_text("file-token")
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            token = _load_or_create_token()
            assert token == "file-token"


def test_token_file_read_error(tmp_path):
    token_file = tmp_path / ".token"
    with patch("tools.gimo_server.config.ORCH_TOKEN_FILE", token_file):
        with patch.dict(os.environ, {"ORCH_TOKEN": ""}):
            with patch.object(Path, "read_text", side_effect=Exception("read error")):
                token = _load_or_create_token()
                assert len(token) > 0
