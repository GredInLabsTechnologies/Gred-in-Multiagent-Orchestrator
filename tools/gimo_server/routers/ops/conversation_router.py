from typing import List, Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from ...ops_models import GimoThread, GimoTurn, GimoItem, GimoItemType
from ...services.conversation_service import ConversationService
from ...security import verify_token
from ...security.auth import AuthContext
from .common import _require_role

router = APIRouter(prefix="/threads", tags=["conversation"])

@router.get("", response_model=List[GimoThread])
async def list_threads(
    auth: Annotated[AuthContext, Depends(verify_token)],
    workspace_root: Annotated[Optional[str], Query()] = None,
):
    """Lists all conversation threads."""
    return ConversationService.list_threads(workspace_root=workspace_root)

@router.post("", response_model=GimoThread, status_code=201)
async def create_thread(
    workspace_root: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    title: str = "New Conversation",
):
    """Creates a new conversation thread."""
    _require_role(auth, "operator")
    return ConversationService.create_thread(workspace_root=workspace_root, title=title)

@router.get("/{thread_id}", response_model=GimoThread, responses={404: {"description": "Thread not found"}})
async def get_thread(
    thread_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Retrieves a specific thread by ID."""
    thread = ConversationService.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread

@router.post("/{thread_id}/turns", response_model=GimoTurn, responses={404: {"description": "Thread not found"}})
async def add_turn(
    thread_id: str,
    agent_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Adds a new turn to a thread."""
    _require_role(auth, "operator")
    turn = ConversationService.add_turn(thread_id, agent_id)
    if not turn:
        raise HTTPException(status_code=404, detail="Thread not found")
    return turn

@router.post("/{thread_id}/turns/{turn_id}/items", status_code=201, responses={404: {"description": "Thread or Turn not found"}})
async def add_item(
    thread_id: str,
    turn_id: str,
    type: GimoItemType,
    auth: Annotated[AuthContext, Depends(verify_token)],
    content: str = "",
):
    """Adds an atomic item to a turn."""
    _require_role(auth, "operator")
    item = GimoItem(type=type, content=content)
    success = ConversationService.append_item(thread_id, turn_id, item)
    if not success:
        raise HTTPException(status_code=404, detail="Thread or Turn not found")
    return item

@router.patch("/{thread_id}/turns/{turn_id}/items/{item_id}", responses={404: {"description": "Item not found"}})
async def update_item(
    thread_id: str,
    turn_id: str,
    item_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    delta: str = "",
    status: Optional[str] = None,
):
    """Updates an item (streaming delta or status change)."""
    _require_role(auth, "operator")
    success = ConversationService.update_item_content(thread_id, turn_id, item_id, delta, status)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "updated"}

@router.post("/{thread_id}/fork", response_model=GimoThread, responses={404: {"description": "Thread or Turn not found"}})
async def fork_thread(
    thread_id: str,
    turn_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    title: Optional[str] = None,
):
    """Forks a thread from a specific turn."""
    _require_role(auth, "operator")
    new_thread = ConversationService.fork_thread(thread_id, turn_id, title)
    if not new_thread:
        raise HTTPException(status_code=404, detail="Thread or Turn not found")
    return new_thread

@router.post("/{thread_id}/messages", responses={404: {"description": "Thread not found"}})
async def post_message(
    thread_id: str,
    content: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Post a new message to a thread (as the user)."""
    _require_role(auth, "operator")
    turn = ConversationService.add_turn(thread_id, agent_id="User")
    if not turn:
        raise HTTPException(status_code=404, detail="Thread not found")
        
    item = GimoItem(type="text", content=content, status="completed")
    ConversationService.append_item(thread_id, turn.id, item)
    
    return {"status": "ok", "turn_id": turn.id}
