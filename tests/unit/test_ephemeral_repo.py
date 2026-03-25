import pytest
from pathlib import Path
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.services.ephemeral_repo_service import EphemeralRepoService

def test_ephemeral_repo_created_outside_source_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    head = GitService.get_head_commit(source)
    
    ephemeral_repos_dir = tmp_path / "ephemeral"
    mirrors_dir = tmp_path / "mirrors"
    quarantine_dir = tmp_path / "quarantine"
    
    svc = EphemeralRepoService(ephemeral_repos_dir, mirrors_dir, quarantine_dir)
    target_dir = svc.create_ephemeral_workspace(source, head, "feature-branch")
    
    assert target_dir.exists()
    assert (target_dir / ".git").exists()
    assert source not in target_dir.parents
    assert target_dir.is_relative_to(ephemeral_repos_dir)
    assert (target_dir / "file.txt").read_text() == "v1"

def test_ephemeral_repo_destroy_removes_workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    head = GitService.get_head_commit(source)

    ephemeral_repos_dir = tmp_path / "ephemeral"
    svc = EphemeralRepoService(ephemeral_repos_dir, tmp_path / "m", tmp_path / "q")
    
    target_dir = svc.create_ephemeral_workspace(source, head, "feature-branch")
    assert target_dir.exists()
    
    svc.destroy_workspace(target_dir)
    assert not target_dir.exists()

def test_git_service_primitives(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    head = GitService.current_head(source)
    
    GitService.clone_local(tmp_path, source, target)
    assert target.exists()
    
    GitService.checkout_commit(target, head)
    assert GitService.current_head(target) == head
    
    GitService.create_ephemeral_branch(target, "test-branch", head)
    assert GitService.current_head(target) == head
    
    assert GitService.clean_repo_check(target) is True

def test_git_service_bundle_diff_apply(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    
    # Init source
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    base_commit = GitService.current_head(source)
    
    # Init target as a clone of source
    GitService.clone_local(tmp_path, source, target)
    
    # Update source
    (source / "file.txt").write_text("v2")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "update")
    head_commit = GitService.current_head(source)
    
    # Create bundle
    bundle_file = tmp_path / "diff.bundle"
    GitService.bundle_diff(source, bundle_file, base_commit, "HEAD")
    assert bundle_file.exists()
    
    # Apply bundle to target
    GitService.apply_bundle(target, bundle_file)
    
    # Verify target has the new commit properties
    assert GitService.current_head(target) == head_commit
    assert (target / "file.txt").read_text() == "v2"
