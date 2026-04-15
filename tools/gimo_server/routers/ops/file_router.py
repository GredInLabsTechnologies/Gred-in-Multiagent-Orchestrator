"""OPS file endpoints — migrated from legacy /tree, /file, /search, /diff."""
from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ...config import ALLOWLIST_REQUIRE, MAX_LINES
from ...security import check_rate_limit, get_active_repo_dir, get_allowed_paths, validate_path
from ...security.validation import get_workspace_from_request
from ...security.auth import AuthContext
from ...services.file_service import FileService
from ...services.repo_service import RepoService
from ..ops.common import require_read

router = APIRouter(prefix="/ops/files", tags=["files"])


@router.get("/tree")
async def get_tree(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    path: str = ".",
    max_depth: int = Query(3, le=6),
):
    base_dir = get_workspace_from_request(request)
    target = validate_path(path, base_dir)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    if ALLOWLIST_REQUIRE:
        allowed_paths = get_allowed_paths(base_dir)
        files = []
        for p in allowed_paths:
            try:
                rel = p.resolve().relative_to(target.resolve())
            except ValueError:
                continue
            files.append(str(rel))
        return {"files": sorted(set(files)), "truncated": False}

    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(None, RepoService.walk_tree, target, max_depth)
    return {"files": files, "truncated": len(files) >= 2000}


@router.get("/content", response_class=PlainTextResponse)
def get_file_content(
    request: Request,
    path: str,
    auth: Annotated[AuthContext, Depends(require_read)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    start_line: int = Query(1, ge=1),
    end_line: int = Query(MAX_LINES, ge=1),
):
    base_dir = get_workspace_from_request(request)
    target = validate_path(path, base_dir)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file.")
    if target.stat().st_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        content, _ = FileService.get_file_content(target, start_line, end_line, auth.token)
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_files(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    q: str = Query(..., min_length=3, max_length=128),
    ext: Optional[str] = None,
):
    base_dir = get_workspace_from_request(request)
    loop = asyncio.get_running_loop()
    hits = await loop.run_in_executor(None, RepoService.perform_search, base_dir, q, ext)
    return {"results": hits, "truncated": len(hits) >= 50}


@router.get("/diff", response_class=PlainTextResponse)
def get_diff(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    base: str = "main",
    head: str = "HEAD",
):
    from ...config import MAX_BYTES
    from ...security import redact_sensitive_data
    from ...services.git_service import GitService

    base_dir = get_workspace_from_request(request)
    try:
        stdout = GitService.get_diff(base_dir, base, head)
        content = redact_sensitive_data(stdout)
        if len(content.encode("utf-8")) > MAX_BYTES:
            content = content[:MAX_BYTES] + "\n# ... [TRUNCATED] ...\n"
        return content
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
