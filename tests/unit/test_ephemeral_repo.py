import pytest
from pathlib import Path
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.services.ephemeral_repo_service import EphemeralRepoService

def test_fetch_mirror_roundtrip(tmp_path):
    # Setup origin
    origin = tmp_path / "origin"
    origin.mkdir()
    GitService._run_git(origin, ["init"])
    (origin / "file.txt").write_text("v1")
    GitService._run_git(origin, ["add", "file.txt"])
    GitService.commit_all(origin, "initial")
    head1 = GitService.current_head(origin)

    # Init mirror
    ephemeral_repos_dir = tmp_path / "ephemeral"
    mirrors_dir = tmp_path / "mirrors"
    quarantine_dir = tmp_path / "quarantine"
    
    svc = EphemeralRepoService(ephemeral_repos_dir, mirrors_dir, quarantine_dir)
    mirror_dir = svc.get_or_update_mirror(str(origin.resolve()), "test-mirror")
    
    assert mirror_dir.exists()
    assert (mirror_dir / "HEAD").exists() # It's a bare repo
    assert not (mirror_dir / ".git").exists()
    
    # Clone from mirror
    target_dir = svc.create_ephemeral_workspace_from_mirror(mirror_dir, head1, "feature-1")
    assert target_dir.exists()
    assert (target_dir / "file.txt").read_text() == "v1"
    
    # Update origin
    (origin / "file.txt").write_text("v2")
    GitService._run_git(origin, ["add", "file.txt"])
    GitService.commit_all(origin, "update")
    head2 = GitService.current_head(origin)
    
    # Fetch into mirror
    svc.get_or_update_mirror(str(origin.resolve()), "test-mirror")
    
    # Clone anew from mirror
    target_dir2 = svc.create_ephemeral_workspace_from_mirror(mirror_dir, head2, "feature-2")
    assert target_dir2.exists()
    assert (target_dir2 / "file.txt").read_text() == "v2"

def test_create_ephemeral_branch_creates_and_checks_out_branch(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    head = GitService.current_head(source)
    
    GitService.clone_local(tmp_path, source, target)
    
    GitService.create_ephemeral_branch(target, "my-ephemeral-branch", head)
    
    assert GitService.current_head(target) == head
    code, out, err = GitService._run_git(target, ["branch", "--show-current"])
    assert code == 0
    assert out.strip() == "my-ephemeral-branch"

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
    
    GitService._run_git(source, ["init"])
    (source / "file.txt").write_text("v1")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "initial")
    base_commit = GitService.current_head(source)
    
    GitService.clone_local(tmp_path, source, target)
    
    (source / "file.txt").write_text("v2")
    GitService._run_git(source, ["add", "file.txt"])
    GitService.commit_all(source, "update")
    head_commit = GitService.current_head(source)
    
    bundle_file = tmp_path / "diff.bundle"
    GitService.bundle_diff(source, bundle_file, base_commit, "HEAD")
    assert bundle_file.exists()
    
    GitService.apply_bundle(target, bundle_file)
    
    assert GitService.current_head(target) == head_commit
    assert (target / "file.txt").read_text() == "v2"
