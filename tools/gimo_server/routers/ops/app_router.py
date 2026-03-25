from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Annotated, List, Optional
from pydantic import BaseModel
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.app_session_service import AppSessionService

router = APIRouter(prefix="/app", tags=["ops.app"]) # Prefix /ops comes from ops_routes.py mount

class AppSessionCreate(BaseModel):
    metadata: Optional[dict] = None

class AppRepoSelection(BaseModel):
    repo_id: str # Opaque handle

@router.post("/sessions")
async def create_session(
    auth: Annotated[AuthContext, Depends(verify_token)],
    data: AppSessionCreate
):
    """P4: Crea una sesión de App file-backed."""
    return AppSessionService.create_session(data.metadata)

@router.get("/sessions/{id}")
async def get_session(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str
):
    """P4: Recupera el estado de una sesión de App."""
    session = AppSessionService.get_session(id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.post("/sessions/{id}/repo/select")
async def select_repo(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    data: AppRepoSelection
):
    """P4: Vincula un repositorio a la sesión usando un handle opaco."""
    if not AppSessionService.bind_repo(id, data.repo_id):
        raise HTTPException(status_code=400, detail="Invalid repo_id or session")
    return {"status": "ok", "repo_id": data.repo_id}

@router.post("/sessions/{id}/drafts")
async def create_draft(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    payload: dict = Body(...)
):
    """P4 Honest Dummy: No implementado todavía."""
    return {"status": "not_implemented", "msg": "Draft creation not yet available in Session surface"}

@router.post("/runs")
async def create_run(
    auth: Annotated[AuthContext, Depends(verify_token)],
    payload: dict = Body(...)
):
    """P4 Honest Dummy: No implementado todavía."""
    return {"status": "not_implemented", "msg": "Run creation via App surface not yet available"}

@router.get("/runs/{run_id}/review")
async def get_run_review(
    auth: Annotated[AuthContext, Depends(verify_token)],
    run_id: str
):
    """P4 Honest Dummy: No implementado todavía."""
    return {"status": "not_implemented", "msg": "Run review not yet available"}

@router.post("/runs/{run_id}/discard")
async def discard_run(
    auth: Annotated[AuthContext, Depends(verify_token)],
    run_id: str
):
    """P4 Honest Dummy: No implementado todavía."""
    return {"status": "not_implemented", "msg": "Run discard not yet available"}

@router.post("/sessions/{id}/purge")
async def purge_session(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str
):
    """P4: Elimina una sesión de App."""
    if not AppSessionService.purge_session(id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "deleted": id}
