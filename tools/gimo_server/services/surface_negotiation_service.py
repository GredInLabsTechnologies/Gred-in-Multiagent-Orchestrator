"""Surface Negotiation Service: Detects and negotiates surface capabilities.

Part of SAGP — maps surface types to capability sets and infers
surface identity from request context (headers, user-agent, transport).
"""
from __future__ import annotations

import logging
from typing import Optional

from ..models.surface import SurfaceIdentity, SurfaceType

logger = logging.getLogger("orchestrator.surface_negotiation")


class SurfaceNegotiationService:
    """Detects surface type and builds SurfaceIdentity with capabilities."""

    SURFACE_CAPABILITIES: dict[str, frozenset[str]] = {
        "claude_app": frozenset({"streaming", "mcp_apps", "hitl_dialog", "agent_teams", "sub_agents"}),
        "vscode": frozenset({"streaming", "mcp_apps", "hitl_dialog"}),
        "cursor": frozenset({"streaming", "hitl_dialog"}),
        "cli": frozenset({"streaming", "hitl_inline", "ansi_colors"}),
        "tui": frozenset({"streaming", "hitl_inline", "ansi_colors", "panels"}),
        "web": frozenset({"streaming", "hitl_dialog", "websocket"}),
        "chatgpt_app": frozenset({"mcp_apps", "hitl_dialog"}),
        "mcp_generic": frozenset(),
        "agent_sdk": frozenset({"streaming", "sub_agents", "hooks"}),
    }

    @classmethod
    def negotiate(cls, surface_type: str, surface_name: str = "") -> SurfaceIdentity:
        """Build SurfaceIdentity with capabilities for a given surface type."""
        if surface_type not in cls.SURFACE_CAPABILITIES:
            surface_type = "mcp_generic"

        capabilities = cls.SURFACE_CAPABILITIES[surface_type]
        return SurfaceIdentity(
            surface_type=surface_type,  # type: ignore[arg-type]
            surface_name=surface_name or surface_type,
            capabilities=capabilities,
        )

    @classmethod
    def infer_surface(
        cls,
        *,
        user_agent: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        transport: Optional[str] = None,
    ) -> str:
        """Detect surface type from request context.

        Returns the surface_type string.
        """
        headers = headers or {}

        # Explicit header takes precedence
        explicit = headers.get("X-Gimo-Surface", "").strip().lower()
        if explicit and explicit in cls.SURFACE_CAPABILITIES:
            return explicit

        # Infer from User-Agent
        ua = (user_agent or headers.get("User-Agent", "")).lower()
        if "claude" in ua and ("code" in ua or "desktop" in ua):
            return "claude_app"
        if "vscode" in ua or "visual studio code" in ua:
            return "vscode"
        if "cursor" in ua:
            return "cursor"
        if "chatgpt" in ua or "openai" in ua:
            return "chatgpt_app"

        # Infer from transport
        if transport:
            t = transport.lower()
            if t == "stdio":
                return "cli"
            if t == "websocket" or t == "ws":
                return "web"

        return "mcp_generic"
