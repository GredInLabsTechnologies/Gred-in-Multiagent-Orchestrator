"""IDE Context Router — Endpoints para capturar y consultar contexto del workspace.

P9: Permite a IDEs (VS Code, JetBrains) reportar eventos de workspace y obtener
análisis de context para routing adaptativo.
"""
from typing import Annotated, Any, Dict
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from ...services.workspace_context_service import WorkspaceContextService
from ...services.context_analysis_service import ContextAnalysisService


class WorkspaceEventRequest(BaseModel):
    """Request model para eventos de workspace."""
    event_type: str = Field(..., description="Tipo de evento (file_open, file_edit, file_close, git_stage, git_commit, terminal_cmd)")
    file_path: str = Field(..., description="Path del archivo afectado")
    timestamp: float = Field(..., description="Timestamp del evento")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata adicional del evento")


router = APIRouter(prefix="/ops/context", tags=["ops", "ide_context"])


@router.post("/event")
async def capture_workspace_event(
    event: WorkspaceEventRequest,
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    auth: Annotated[AuthContext, Depends(verify_token)] = None
) -> Dict[str, Any]:
    """Captura evento del IDE.

    Headers:
        X-Session-ID: ID de sesión del workspace (optional, defaults to cli-{role})

    Request body:
        {
            "event_type": "file_open|file_edit|file_close|git_stage|git_commit|terminal_cmd",
            "file_path": "src/services/auth.py",
            "timestamp": 1735689600.123,
            "metadata": {
                "lines_changed": 15,
                "git_ref": "feat/auth",
                "command": "pytest tests/"
            }
        }
    """
    effective_session = session_id or f"cli-{auth.role}"
    WorkspaceContextService.capture_event(
        session_id=effective_session,
        event_type=event.event_type,
        file_path=event.file_path,
        metadata=event.metadata,
    )

    return {"status": "captured", "session_id": effective_session}


@router.get("/recent-files")
async def get_recent_files(
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    auth: Annotated[AuthContext, Depends(verify_token)] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """Obtiene archivos recientes con temporal weights.

    Headers:
        X-Session-ID: ID de sesión del workspace (optional, defaults to cli-{role})

    Query:
        limit: Máximo número de archivos (default 10)

    Returns:
        {
            "recent_files": [
                {
                    "file_path": str,
                    "last_access_at": float,
                    "access_count": int,
                    "temporal_weight": float
                },
                ...
            ],
            "count": int
        }
    """
    effective_session = session_id or f"cli-{auth.role}"
    files = WorkspaceContextService.get_recent_files(effective_session, limit=limit)
    return {"recent_files": files, "count": len(files)}


@router.get("/focus-cluster")
async def get_active_focus_cluster(
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    auth: Annotated[AuthContext, Depends(verify_token)] = None
) -> Dict[str, Any]:
    """Obtiene cluster activo de trabajo.

    Headers:
        X-Session-ID: ID de sesión del workspace (optional, defaults to cli-{role})

    Returns:
        {
            "cluster": {
                "cluster_id": str,
                "files": List[str],
                "semantic_label": str,
                "last_activity_at": float
            } | null
        }
    """
    effective_session = session_id or f"cli-{auth.role}"
    cluster = WorkspaceContextService.get_active_focus_cluster(effective_session)
    return {"cluster": cluster}


@router.get("/sequences")
async def get_detected_sequences(
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    auth: Annotated[AuthContext, Depends(verify_token)] = None,
    min_support: int = 3
) -> Dict[str, Any]:
    """Obtiene file sequences detectadas.

    Headers:
        X-Session-ID: ID de sesión del workspace (optional, defaults to cli-{role})

    Query:
        min_support: Mínimo número de occurrences (default 3)

    Returns:
        {
            "sequences": [
                {
                    "sequence": ["model.py", "test_model.py", "conftest.py"],
                    "occurrences": int,
                    "confidence": float,
                    "last_seen_at": float
                },
                ...
            ],
            "count": int
        }
    """
    effective_session = session_id or f"cli-{auth.role}"
    sequences = ContextAnalysisService.get_detected_sequences(
        effective_session, min_support=min_support
    )
    return {"sequences": sequences, "count": len(sequences)}


@router.get("/git-status")
async def get_git_status(
    session_id: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    auth: Annotated[AuthContext, Depends(verify_token)] = None
) -> Dict[str, Any]:
    """Obtiene git status del workspace.

    Headers:
        X-Session-ID: ID de sesión del workspace (optional, defaults to cli-{role})

    Returns:
        {
            "git_status": {
                "staged_files": List[str],
                "unstaged_files": List[str],
                "branch": str,
                "last_commit_at": float
            } | null
        }
    """
    effective_session = session_id or f"cli-{auth.role}"
    status = WorkspaceContextService.get_git_status(effective_session)
    return {"git_status": status}
