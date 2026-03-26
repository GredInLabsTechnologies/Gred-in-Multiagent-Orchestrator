from fastapi import APIRouter, Depends, HTTPException, Body, Query
from typing import Annotated, List, Optional
from pydantic import BaseModel
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.repo_recon_service import RepoReconService
from tools.gimo_server.services.draft_validation_service import DraftValidationService
from tools.gimo_server.services.context_request_service import ContextRequestService
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.review_merge_service import ReviewMergeService
from tools.gimo_server.services.purge_service import PurgeService

from tools.gimo_server.schemas.repo_recon import ReconEntry, FileContentResponse
from tools.gimo_server.schemas.draft_validation import DraftCreateRequest, DraftValidationResponse
from tools.gimo_server.schemas.context_request import ContextCreateRequest, ContextRequestEntry, ContextResolveRequest, ContextCancelRequest

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

# --- P5.1 RECON SERVICE ---
@router.get("/sessions/{id}/recon/list", response_model=List[ReconEntry])
async def list_repo_files(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    path_handle: Optional[str] = Query(None)
):
    """P5.1 Recon: Lista archivos del repositorio vinculado usando handles opacos."""
    try:
        return RepoReconService.list_files(id, path_handle)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions/{id}/recon/search")
async def search_repo_files(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    q: str = Query(...)
):
    """P5.1 Recon: Busca contenido en el repositorio vinculado."""
    try:
        return RepoReconService.search(id, q)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions/{id}/recon/read/{file_handle}", response_model=FileContentResponse)
async def read_repo_file(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    file_handle: str
):
    """P5.1 Recon: Lee un archivo y genera un ReadProof persistente."""
    try:
        return RepoReconService.read_file(id, file_handle)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- P5.2 VALIDATION SERVICE ---
@router.post("/sessions/{id}/drafts", response_model=DraftValidationResponse)
async def create_draft(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    payload: DraftCreateRequest
):
    """P5.2 Validation: Valida el draft apoyándose en evidencia (ReadProofs) de Recon."""
    try:
        return DraftValidationService.validate_draft(id, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- P5.3 CONTEXT REQUEST SERVICE ---
@router.post("/sessions/{id}/context-requests", response_model=ContextRequestEntry)
async def create_context_request(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    data: ContextCreateRequest
):
    """P5.3 Context: Crea una solicitud persistente de contexto adicional."""
    try:
        return ContextRequestService.create_request(id, data.description, data.metadata)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions/{id}/context-requests", response_model=List[ContextRequestEntry])
async def list_context_requests(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    status: Optional[str] = Query(None)
):
    """P5.3 Context: Lista solicitudes de contexto de la sesión."""
    return ContextRequestService.list_requests(id, status)

@router.post("/sessions/{id}/context-requests/{req_id}/resolve")
async def resolve_context_request(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    req_id: str,
    data: ContextResolveRequest
):
    """P5.3 Context: Marca una solicitud como resuelta."""
    if ContextRequestService.resolve_request(id, req_id, data.evidence):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Request not found")

@router.post("/sessions/{id}/context-requests/{req_id}/cancel")
async def cancel_context_request(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str,
    req_id: str,
    data: ContextCancelRequest
):
    """P5.3 Context: Cancela una solicitud."""
    if ContextRequestService.cancel_request(id, req_id, data.reason):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Request not found")

# --- P6/P7 RUN OPERATIONS ---
@router.post("/runs/{run_id}/execute")
async def execute_run(
    auth: Annotated[AuthContext, Depends(verify_token)],
    run_id: str
):
    """P7: Dispara la ejecución del pipeline de merge gate de forma asíncrona."""
    # En un entorno de producción, esto debería encolarse en un task worker.
    # Por ahora invocamos el gate service de forma directa para validación del lifecycle.
    try:
        success = await MergeGateService.execute_run(run_id)
        return {"status": "ok" if success else "failed", "run_id": run_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/runs/{run_id}/review")
async def get_run_review(
    auth: Annotated[AuthContext, Depends(verify_token)],
    run_id: str
):
    """P6A: Recupera el bundle de revisión y el preview del merge."""
    try:
        preview = ReviewMergeService.get_merge_preview(run_id)
        bundle = ReviewMergeService.build_review_bundle(run_id)
        return {
            "preview": preview.model_dump(),
            "bundle": {
                "base_commit": bundle.base_commit,
                "head_commit": bundle.head_commit,
                "changed_files": bundle.changed_files,
                "drift_detected": bundle.drift_detected
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/runs/{run_id}/discard")
async def discard_run(
    auth: Annotated[AuthContext, Depends(verify_token)],
    run_id: str
):
    """P6B: Descarta un run y purga su estado reconstructivo (PurgeService)."""
    try:
        receipt = PurgeService.purge_run(run_id)
        return {"status": "ok", "receipt": receipt.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sessions/{id}/purge")
async def purge_session(
    auth: Annotated[AuthContext, Depends(verify_token)],
    id: str
):
    """P4: Elimina una sesión de App."""
    if not AppSessionService.purge_session(id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "deleted": id}

