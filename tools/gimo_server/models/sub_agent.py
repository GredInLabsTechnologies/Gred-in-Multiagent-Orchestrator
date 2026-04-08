"""Sub-agent lifecycle models."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class SubAgentConfig(BaseModel):
    """Configuration for a sub-agent instance."""
    model: str = "qwen2.5-coder:3b"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_seconds: int = 300


class SubAgent(BaseModel):
    """Runtime state of a spawned sub-agent."""
    id: str
    parentId: str
    name: str = ""
    model: str = "qwen2.5-coder:3b"
    status: str = "starting"  # starting, idle, working, failed, terminated, offline
    config: SubAgentConfig = Field(default_factory=SubAgentConfig)
    worktreePath: Optional[str] = None
    description: str = ""
    currentTask: Optional[str] = None
    result: Optional[str] = None
    provider: Optional[str] = None
    executionPolicy: Optional[str] = None
    draftId: Optional[str] = None
    runId: Optional[str] = None
    routing: Dict[str, Any] = Field(default_factory=dict)
    delegation: Dict[str, Any] = Field(default_factory=dict)
    authority: str = "ops_run"
    # R20-007: inventory schema discriminator. "auto_discovery" = pulled from
    # an installed Ollama / local catalog on startup; "spawn" = created via
    # governed spawn_via_draft. Required so UI/MCP callers can filter out
    # orphan spawn records accumulated from failed runs.
    source: Literal["auto_discovery", "spawn"] = "spawn"
