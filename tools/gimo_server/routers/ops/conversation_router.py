import json
from typing import List, Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from ...ops_models import GimoThread, GimoTurn, GimoItem, GimoItemType
from ...services.conversation_service import ConversationService
from ...services.agentic_loop_service import AgenticLoopService, ThreadExecutionBusyError
from ...services.task_descriptor_service import TaskDescriptorService
from ...security import verify_token
from ...security.auth import AuthContext
from .common import _require_role
from ...services.thread_session_service import ThreadSessionService

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


@router.get("/{thread_id}/proofs", responses={404: {"description": "Thread not found"}})
async def get_thread_proofs(
    thread_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    thread = ConversationService.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return AgenticLoopService.get_thread_proofs(thread_id)

@router.post("/{thread_id}/turns", response_model=GimoTurn, responses={404: {"description": "Thread not found"}})
async def add_turn(
    thread_id: str,
    agent_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Adds a new turn to a thread."""
    _require_role(auth, "operator")
    try:
        turn = ConversationService.add_turn(thread_id, agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

@router.post("/{thread_id}/chat", responses={404: {"description": "Thread not found"}})
async def chat_message(
    thread_id: str,
    content: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """
    Send a message and get an agentic response with tool execution.

    This is the main endpoint for GIMO CLI interactive chat.
    """
    _require_role(auth, "operator")

    thread = ConversationService.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Run agentic loop
    token = getattr(auth, "actor", None) or "CLI"
    try:
        result = await AgenticLoopService.run(
            thread_id=thread_id,
            user_message=content,
            workspace_root=thread.workspace_root,
            token=token,
        )
    except ThreadExecutionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "status": "ok",
        "response": result.response,
        "tool_calls": result.tool_calls_log,
        "usage": result.usage,
        "finish_reason": result.finish_reason
    }


@router.post("/{thread_id}/chat/stream", responses={404: {"description": "Thread not found"}})
async def chat_message_stream(
    thread_id: str,
    content: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """
    Send a message and stream the agentic response via SSE.

    Emits events: session_start, iteration_start, text_delta,
    tool_call_start, tool_call_end, tool_approval_required, error, done.
    """
    _require_role(auth, "operator")

    thread = ConversationService.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    token = getattr(auth, "actor", None) or "CLI"

    try:
        reservation = AgenticLoopService.reserve_thread_execution(thread_id)
    except ThreadExecutionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    owner_id = str(reservation.get("owner_id") or "")
    stop_event, heartbeat_task = AgenticLoopService._start_thread_execution_heartbeat(thread_id, owner_id)

    async def event_generator():
        try:
            async for event in AgenticLoopService._run_stream_reserved(
                thread_id=thread_id,
                user_message=content,
                workspace_root=thread.workspace_root,
                token=token,
            ):
                event_type = event.get("event", "message")
                data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
        finally:
            await AgenticLoopService._stop_heartbeat(stop_event, heartbeat_task)
            AgenticLoopService.release_thread_execution(thread_id, owner_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{thread_id}/approve-tool", responses={404: {"description": "Approval not found"}})
async def approve_tool(
    thread_id: str,
    tool_call_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    approved: bool = True,
):
    """
    Approve or deny a pending HIGH-risk tool call (HITL).
    """
    _require_role(auth, "operator")

    success = AgenticLoopService.submit_approval(thread_id, tool_call_id, approved)
    if not success:
        raise HTTPException(status_code=404, detail="No pending approval found for this tool call")

    return {"status": "ok", "approved": approved, "tool_call_id": tool_call_id}


# ── P2: Plan Approval Endpoint ────────────────────────────────────────────────

@router.post("/{thread_id}/plan/respond", responses={404: {"description": "Thread or plan not found"}})
async def respond_to_plan(
    thread_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    action: str,  # "approve", "reject", "modify"
    feedback: str = "",
    modified_plan: Optional[dict] = None,
):
    """
    P2: Respond to a proposed plan.

    Actions:
    - "approve": Execute the plan as proposed
    - "reject": Reject the plan and provide feedback to the agent
    - "modify": Update specific tasks in the plan (provide modified_plan)

    The agent will resume from the paused state based on the response.
    """
    _require_role(auth, "operator")

    thread = ConversationService.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if not thread.proposed_plan:
        raise HTTPException(status_code=404, detail="No proposed plan found in this thread")

    if action == "approve":
        # Create the plan for execution using CustomPlanService
        from ...services.custom_plan_service import CustomPlanService

        try:
            proposed_plan = thread.proposed_plan or {}
            canonical_plan = TaskDescriptorService.canonicalize_plan_data(proposed_plan)
            persisted = ConversationService.mutate_thread(
                thread_id,
                lambda current: setattr(current, "proposed_plan", canonical_plan) or True,
            )
            if persisted is None:
                raise HTTPException(status_code=404, detail="Thread not found")
            plan = CustomPlanService.create_plan_from_llm(
                plan_data=canonical_plan,
                name=canonical_plan.get("title", "Approved Plan"),
                description=canonical_plan.get("objective", ""),
            )

            updated = ConversationService.mutate_thread(
                thread_id,
                lambda current: (
                    setattr(current, "proposed_plan", canonical_plan),
                    setattr(current, "workflow_phase", "executing"),
                    current.metadata.__setitem__("plan_approved", True),
                    current.metadata.__setitem__("plan_approved_at", json.dumps({"time": "now"})),
                ),
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Thread not found")

            # Execute plan in background
            import asyncio
            asyncio.create_task(CustomPlanService.execute_plan(plan.id))

            return {
                "status": "approved",
                "message": "Plan approved and execution started",
                "plan_id": plan.id,
                "workflow_phase": "executing",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create plan: {str(e)}")

    elif action == "reject":
        # Clear proposed plan, add rejection feedback to thread
        ConversationService.mutate_thread(
            thread_id,
            lambda current: (
                setattr(current, "proposed_plan", None),
                setattr(current, "workflow_phase", "planning"),
            ),
        )

        # Add rejection as user message so agent can re-plan
        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if user_turn:
            rejection_msg = f"[PLAN REJECTED] {feedback or 'Plan rejected. Please revise.'}"
            item = GimoItem(type="text", content=rejection_msg, status="completed")
            ConversationService.append_item(thread_id, user_turn.id, item)

        return {
            "status": "rejected",
            "message": "Plan rejected. Agent will revise.",
            "workflow_phase": "planning",
        }

    elif action == "modify":
        if not modified_plan:
            raise HTTPException(status_code=400, detail="modified_plan required for 'modify' action")

        # Update proposed plan with user modifications
        try:
            canonical_plan = TaskDescriptorService.canonicalize_plan_data(modified_plan)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid modified plan: {str(e)}") from e
        ConversationService.mutate_thread(
            thread_id,
            lambda current: setattr(current, "proposed_plan", canonical_plan),
        )

        return {
            "status": "modified",
            "message": "Plan updated with your changes. Review again or approve.",
            "modified_plan": canonical_plan,
        }

    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}. Must be 'approve', 'reject', or 'modify'.")

# ── P2: Canonical Thread/Session Contracts ────────────────────────────────────

@router.post("/{thread_id}/reset")
async def reset_thread(
    thread_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """P2: Resets thread context without destroying thread identity."""
    _require_role(auth, "operator")
    success = ThreadSessionService.reset_thread(thread_id)
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}

@router.post("/{thread_id}/config")
async def config_thread(
    thread_id: str,
    config_data: dict,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """P2: Updates thread session configuration like effort and permission modes."""
    _require_role(auth, "operator")
    try:
        success = ThreadSessionService.update_config(thread_id, config_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}

@router.post("/{thread_id}/context/add")
async def add_context(
    thread_id: str,
    context_data: dict,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """P2: Appends context elements (e.g. files) to the thread."""
    _require_role(auth, "operator")
    success = ThreadSessionService.add_context(thread_id, context_data)
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}

@router.get("/{thread_id}/usage")
async def get_usage(
    thread_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """P2: Returns an aggregated usage snapshot for the thread."""
    _require_role(auth, "operator")
    usage = ThreadSessionService.get_usage(thread_id)
    if usage is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return usage
