from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.gimo_server.services.git_service import GitService


def test_get_diff_success(tmp_path):
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("stat info", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        diff = GitService.get_diff(tmp_path)
        assert diff == "stat info"


def test_get_diff_git_error(tmp_path):
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "error message")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        with pytest.raises(RuntimeError) as exc:
            GitService.get_diff(tmp_path)
        assert "Git error: error message" in str(exc.value)


def test_get_diff_exception(tmp_path):
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = Exception("crash")

        with pytest.raises(RuntimeError) as exc:
            GitService.get_diff(tmp_path)
        assert "Internal git execution error: crash" in str(exc.value)


def test_list_repos(tmp_path):
    (tmp_path / "repo1").mkdir()
    (tmp_path / "repo2").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "file.txt").write_text("not a dir")

    repos = GitService.list_repos(tmp_path)
    assert len(repos) == 2
    assert repos[0]["name"] == "repo1"
    assert repos[1]["name"] == "repo2"


def test_list_repos_not_exists():
    assert GitService.list_repos(Path("/nonexistent/path")) == []
