from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class AgentStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class ProposedAction:
    id: str
    tool: str
    params: Dict[str, Any]
    description: Optional[str] = None


@dataclass
class AgentResult:
    status: AgentStatus
    output: Any
    metrics: Dict[str, Any]
    error: Optional[str] = None


class AgentSession(ABC):
    """Represents an active agent execution session."""

    @abstractmethod
    async def get_status(self) -> AgentStatus:
        """Get current session status."""

    @abstractmethod
    async def capture_proposals(self) -> List[ProposedAction]:
        """Capture proposed actions from the agent."""

    @abstractmethod
    async def allow(self, action_id: str) -> None:
        """Allow a specific action to execute."""

    @abstractmethod
    async def deny(self, action_id: str, reason: Optional[str] = None) -> None:
        """Deny a specific action."""

    @abstractmethod
    async def get_result(self) -> AgentResult:
        """Get the final result of the session."""

    @abstractmethod
    async def kill(self) -> None:
        """Forcefully terminate the session."""


class AgentAdapter(ABC):
    """Abstract interface for agent orchestration."""

    @abstractmethod
    async def spawn(
        self, 
        task: str, 
        context: Optional[Dict[str, Any]] = None, 
        policy: Optional[Dict[str, Any]] = None
    ) -> AgentSession:
        """Spawn a new agent session for a given task."""
