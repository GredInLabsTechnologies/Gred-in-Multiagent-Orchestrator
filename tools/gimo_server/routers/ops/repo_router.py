"""OPS repo endpoints — migrated from legacy /ui/repos/*."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...config import REPO_ROOT_DIR
from ...models import VitaminizeResponse
from ...security import (
    audit_log,
    check_rate_limit,
    load_repo_registry,
    save_repo_registry,
)
from ...security.auth import AuthContext
from ...services.repo_service import RepoService
from ...services.repo_override_service import RepoOverrideService
from ..ops.common import require_admin, require_read, require_operator

router = APIRouter(prefix="/ops/repos", tags=["repos"])


def _is_path_within_base(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _is_registered_repo_path(path: Path) -> bool:
    try:
        registry = load_repo_registry()
        registered = {str(Path(p).resolve()) for p in registry.get("repos", [])}
        return str(path.resolve()) in registered
    except Exception:
        return False


def _sanitize_path(path_str: str) -> str:
    if not path_str:
        return path_str
    path_str = re.sub(r"C:\\Users\\[^\\]+", r"C:\\Users\\[USER]", path_str)
    path_str = re.sub(r"/home/[^/]+", "/home/[USER]", path_str)
    path_str = re.sub(r"/Users/[^/]+", "/Users/[USER]", path_str)
    return path_str


@router.get("")
def list_repos(
    auth: AuthContext = Depends(require_read),
    _rl: None = Depends(check_rate_limit),
):
    repos = RepoService.list_repos()
    registry = load_repo_registry()

    current_paths = {str(Path(p).resolve()) for p in registry.get("repos", [])}
    changed = False
    new_repos_list = list(registry.get("repos", []))

    for r in repos:
        raw_path = (r.path or "").strip()
        if not raw_path:
            continue
        try:
            rp = str(Path(raw_path).resolve())
            if rp not in current_paths:
                new_repos_list.append(rp)
                current_paths.add(rp)
                changed = True
        except ValueError:
            pass

    merged_paths: set[str] = set()
    merged_repos: list[dict[str, str]] = []
    empty_path_repos: list[dict[str, str]] = []
    for r in repos:
        raw_path = (r.path or "").strip()
        if not raw_path:
            empty_path_repos.append({"name": r.name, "path": ""})
            continue
        try:
            rp = str(Path(raw_path).resolve())
            if rp not in merged_paths:
                merged_paths.add(rp)
                merged_repos.append({"name": r.name, "path": rp})
        except Exception:
            continue

    for p in registry.get("repos", []):
        try:
            resolved = Path(p).resolve()
            if not resolved.exists() or not resolved.is_dir():
                continue
            rp = str(resolved)
            if rp in merged_paths:
                continue
            merged_paths.add(rp)
            merged_repos.append({"name": resolved.name, "path": rp})
        except Exception:
            continue

    merged_repos.extend(empty_path_repos)

    if changed:
        registry["repos"] = new_repos_list
        save_repo_registry(registry)

    active_repo = registry.get("active_repo")

    return {
        "root": _sanitize_path(str(REPO_ROOT_DIR)),
        "active_repo": _sanitize_path(active_repo) if active_repo else None,
        "repos": [{"name": r["name"], "path": _sanitize_path(r["path"])} for r in merged_repos],
    }


@router.post("/register")
def register_repo(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read),
    _rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(status_code=404, detail="Repo not found")

    registry = load_repo_registry()
    repos = list(registry.get("repos", []))
    rp = str(repo_path)
    if rp not in repos:
        repos.append(rp)
        registry["repos"] = repos
        save_repo_registry(registry)

    audit_log("REPO", "REGISTER", rp, actor=auth.token)
    return {"status": "success", "path": rp}


@router.get("/active")
def get_active_repo(
    auth: AuthContext = Depends(require_read),
    _rl: None = Depends(check_rate_limit),
):
    from fastapi.responses import JSONResponse

    override = RepoOverrideService.get_active_override()
    if override:
        payload = {
            "active_repo": override.get("repo_id"),
            "override_active": True,
            "etag": override.get("etag"),
            "expires_at": override.get("expires_at"),
            "set_by_user": override.get("set_by_user"),
        }
        return JSONResponse(payload, headers={"ETag": str(override.get("etag", ""))})

    registry = load_repo_registry()
    return {
        "active_repo": registry.get("active_repo"),
        "override_active": False,
        "etag": None,
        "expires_at": None,
        "set_by_user": None,
    }


@router.post("/open") # [LEGACY/ADMIN_ONLY]
def open_repo(
    path: str = Query(...),
    auth: AuthContext = Depends(require_admin),
    _rl: None = Depends(check_rate_limit),
):
    """[LEGACY][ADMIN ONLY] Open repo by local filesystem path.
    Canonical client flows must not bind repos via host paths.
    """
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR):
        raise HTTPException(status_code=400, detail="Repo outside of allowed base")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo not found")

    audit_log("UI", "OPEN_REPO", str(repo_path), actor=auth.token)
    return {"status": "success", "message": "Repo signaled for opening (server-agnostic)"}


@router.post("/select") # [LEGACY/ADMIN_ONLY]
def select_repo(
    path: str = Query(...),
    request: Request = None,
    auth: AuthContext = Depends(require_admin),
    _rl: None = Depends(check_rate_limit),
):
    """[LEGACY][ADMIN ONLY] Select active repo by local filesystem path.
    Canonical client flows must not bind repos via host paths.
    """
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR) and not _is_registered_repo_path(repo_path):
        raise HTTPException(status_code=400, detail="Repo outside of allowed base")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo not found")

    if_match_etag = request.headers.get("if-match") if request else None
    try:
        new_override = RepoOverrideService.set_human_override(
            repo_id=str(repo_path),
            set_by_user=auth.token,
            source="api",
            reason="manual_select",
            if_match_etag=if_match_etag,
        )
    except ValueError as exc:
        if str(exc) == "OVERRIDE_ETAG_MISMATCH":
            raise HTTPException(status_code=409, detail="OVERRIDE_ETAG_MISMATCH")
        raise

    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)

    audit_log("REPO", "SELECT", str(repo_path), actor=auth.token)
    return {
        "status": "success",
        "active_repo": str(repo_path),
        "override_active": True,
        "etag": new_override.get("etag"),
        "expires_at": new_override.get("expires_at"),
    }


@router.post("/revoke")
def revoke_override(
    request: Request,
    auth: AuthContext = Depends(require_operator),
    _rl: None = Depends(check_rate_limit),
):
    if_match_etag = request.headers.get("if-match")
    try:
        revoked = RepoOverrideService.revoke_human_override(
            actor=auth.token,
            if_match_etag=if_match_etag,
        )
    except ValueError as exc:
        if str(exc) == "OVERRIDE_ETAG_MISMATCH":
            raise HTTPException(status_code=409, detail="OVERRIDE_ETAG_MISMATCH")
        raise

    return {"status": "success" if revoked else "noop", "revoked": revoked}


@router.post("/vitaminize", response_model=VitaminizeResponse)
def vitaminize_repo(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read),
    _rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR) and not _is_registered_repo_path(repo_path):
        raise HTTPException(status_code=400, detail="Repo outside of allowed base")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo not found")

    created = RepoService.vitaminize_repo(repo_path)

    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)

    audit_log("REPO", "VITAMINIZE", str(repo_path), actor=auth.token)
    return {"status": "success", "created_files": created, "active_repo": str(repo_path)}
