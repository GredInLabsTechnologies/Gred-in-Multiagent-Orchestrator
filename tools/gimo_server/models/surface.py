"""SurfaceIdentity: Identifies the client surface consuming GIMO governance.

SAGP (Surface-Agnostic Governance Protocol) requires every request to declare
which surface is calling so the gateway can adapt responses, enforce
capability-aware constraints, and route HITL appropriately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
import uuid

SurfaceType = Literal[
    "claude_app",
    "vscode",
    "cursor",
    "cli",
    "tui",
    "web",
    "chatgpt_app",
    "mcp_generic",
    "agent_sdk",
]


@dataclass(frozen=True)
class SurfaceIdentity:
    """Immutable identity of a client surface.

    Created once per session/request and propagated through the governance
    pipeline so every service knows who is asking.
    """

    surface_type: SurfaceType
    surface_name: str  # e.g. "Claude Code 1.2.3", "gimo-cli 0.9"
    capabilities: frozenset[str] = field(default_factory=frozenset)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Capability queries ────────────────────────────────────────────────

    def supports(self, capability: str) -> bool:
        """Check if this surface supports a given capability."""
        return capability in self.capabilities

    @property
    def supports_streaming(self) -> bool:
        return "streaming" in self.capabilities

    @property
    def supports_mcp_apps(self) -> bool:
        return "mcp_apps" in self.capabilities

    @property
    def supports_hitl(self) -> bool:
        return "hitl_inline" in self.capabilities or "hitl_dialog" in self.capabilities

    @property
    def supports_agent_teams(self) -> bool:
        return "agent_teams" in self.capabilities
