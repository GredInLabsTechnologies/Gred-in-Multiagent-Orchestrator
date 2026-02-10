from pathlib import Path
from unittest.mock import patch

import pytest

from tools.gimo_server.models import RepoEntry
from tools.gimo_server.services.repo_service import RepoService


@pytest.fixture
def mock_base_dir(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "tools" / "gimo_server").mkdir(parents=True)
    return base


@patch("tools.gimo_server.services.repo_service.GitService.list_repos")
def test_list_repos(mock_list):
    mock_list.return_value = [{"name": "repo1", "path": "/path/1"}]
    repos = RepoService.list_repos()
    assert len(repos) == 1
    assert repos[0].name == "repo1"
    assert repos[0].path == "/path/1"
    assert isinstance(repos[0], RepoEntry)


@patch("tools.gimo_server.services.repo_service.load_repo_registry")
@patch("tools.gimo_server.services.repo_service.save_repo_registry")
def test_ensure_repo_registry(mock_save, mock_load, tmp_path):
    repo_path = tmp_path / "new"
    # Case: active_repo not in current list
    mock_load.return_value = {
        "active_repo": str(tmp_path / "outside"),
        "repos": [str(tmp_path / "old")],
    }
    repos = [RepoEntry(name="new", path=str(repo_path))]

    registry = RepoService.ensure_repo_registry(repos)
    # Normalize paths for comparison
    registry_repos = [str(Path(p).resolve()) for p in registry["repos"]]
    assert str(repo_path.resolve()) in registry_repos
    assert registry.get("active_repo") == str((tmp_path / "outside").resolve())
    mock_save.assert_called_once()


@patch("tools.gimo_server.services.repo_service.BASE_DIR")
@patch("tools.gimo_server.services.repo_service.VITAMINIZE_PACKAGE", {"file.py", "dir"})
def test_vitaminize_repo(mock_base, tmp_path):
    # Note: VITAMINIZE_PACKAGE patch with value doesn't pass a mock argument
    target = tmp_path / "target"
    target.mkdir()

    source_base = tmp_path / "source"
    source_base.mkdir()
    (source_base / "file.py").write_text("content")
    (source_base / "dir").mkdir()
    (source_base / "dir" / "inner.txt").write_text("inner")

    mock_base.return_value = source_base
    # Fix: BASE_DIR in the code is used as source = BASE_DIR / rel
    with patch("tools.gimo_server.services.repo_service.BASE_DIR", source_base):
        created = RepoService.vitaminize_repo(target)
        assert len(created) == 2
        assert (target / "file.py").exists()
        assert (target / "dir").exists()

        # Test skip existing
        created_second = RepoService.vitaminize_repo(target)
        assert len(created_second) == 0


def test_walk_tree(tmp_path):
    (tmp_path / "file.py").write_text("py")
    (tmp_path / "file.ts").write_text("ts")
    (tmp_path / "ignored.txt").write_text("txt")
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "deep.py").write_text("deep")

    files = RepoService.walk_tree(tmp_path, max_depth=2)
    assert "file.py" in files
    assert "file.ts" in files
    assert "subdir\\deep.py" in files or "subdir/deep.py" in files
    assert "ignored.txt" not in files
    assert ".git" not in files

    # Test max_depth
    files_shallow = RepoService.walk_tree(tmp_path, max_depth=0)
    assert not any("subdir" in f for f in files_shallow)

    # Test limit 2000
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [(str(tmp_path), [], ["file.py"] * 2100)]
        files_limited = RepoService.walk_tree(tmp_path, max_depth=1)
        assert len(files_limited) == 2000


def test_perform_search(tmp_path):
    (tmp_path / "test.py").write_text("line1\nsecret_key = 123\nline3")

    hits = RepoService.perform_search(tmp_path, "secret_key", None)
    assert len(hits) == 1
    assert hits[0]["file"] == "test.py"
    assert hits[0]["line"] == 2
    assert "secret_key" in hits[0]["content"]

    # Test ext filter
    hits_ts = RepoService.perform_search(tmp_path, "secret_key", ".ts")
    assert len(hits_ts) == 0

    # Test limit 50
    (tmp_path / "large.py").write_text("match\n" * 60)
    hits_large = RepoService.perform_search(tmp_path, "match", None)
    assert len(hits_large) == 50

    # Test suffix skip (Line 95)
    (tmp_path / "skip.txt").write_text("match")
    hits_skip = RepoService.perform_search(tmp_path, "match", None)
    # Should not include skip.txt because it's not in ALLOWED_EXTENSIONS
    assert not any("skip.txt" in h["file"] for h in hits_skip)


def test_search_in_file_error(tmp_path):
    # Test exception handling (e.g. file not found if deleted between walk and search)
    non_existent = tmp_path / "none.py"
    hits = RepoService._search_in_file(non_existent, tmp_path, "query")
    assert hits == []


def test_should_skip_dir():
    assert RepoService._should_skip_dir(".git") == True
    assert RepoService._should_skip_dir("node_modules") == True
    assert RepoService._should_skip_dir("src") == False
