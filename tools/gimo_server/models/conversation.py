from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field

GimoItemType = Literal["text", "tool_call", "tool_result", "diff", "thought", "error"]
GimoItemStatus = Literal["started", "delta", "completed", "error"]
GimoThreadStatus = Literal["active", "archived", "deleted"]

class GimoItem(BaseModel):
    id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")
    type: GimoItemType
    content: str = ""
    status: GimoItemStatus = "completed"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GimoTurn(BaseModel):
    id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    agent_id: str
    items: List[GimoItem] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GimoThread(BaseModel):
    id: str = Field(default_factory=lambda: f"thread_{uuid.uuid4().hex[:8]}")
    title: str = "New Conversation"
    workspace_root: str
    turns: List[GimoTurn] = Field(default_factory=list)
    status: GimoThreadStatus = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # P2: Mood-driven conversational flow
    mood: str = "neutral"  # Current mood of the agent (neutral, forensic, executor, dialoger, creative, guardian, mentor)
    proposed_plan: Dict[str, Any] | None = None  # Plan proposed by propose_plan tool, awaiting approval
