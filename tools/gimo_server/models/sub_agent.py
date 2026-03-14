"""Sub-agent lifecycle models."""
from __future__ import annotations
from typing import Optional
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
