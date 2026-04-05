"""Unit tests for SurfaceNegotiationService — surface detection and capability negotiation."""

import pytest

from tools.gimo_server.models.surface import SurfaceIdentity
from tools.gimo_server.services.surface_negotiation_service import SurfaceNegotiationService


class TestNegotiate:
    def test_claude_app_capabilities(self):
        surface = SurfaceNegotiationService.negotiate("claude_app", "Claude Code 1.2")
        assert surface.surface_type == "claude_app"
        assert surface.supports_streaming
        assert surface.supports_mcp_apps
        assert surface.supports_agent_teams

    def test_cli_capabilities(self):
        surface = SurfaceNegotiationService.negotiate("cli", "gimo-cli")
        assert surface.supports("ansi_colors")
        assert surface.supports("hitl_inline")
        assert not surface.supports_mcp_apps

    def test_unknown_type_falls_back_to_mcp_generic(self):
        surface = SurfaceNegotiationService.negotiate("unknown_surface", "test")
        assert surface.surface_type == "mcp_generic"
        assert surface.capabilities == frozenset()

    def test_web_capabilities(self):
        surface = SurfaceNegotiationService.negotiate("web", "gimo-web")
        assert surface.supports("websocket")
        assert surface.supports_streaming

    def test_vscode_capabilities(self):
        surface = SurfaceNegotiationService.negotiate("vscode")
        assert surface.supports_streaming
        assert surface.supports_mcp_apps
        assert not surface.supports_agent_teams


class TestInferSurface:
    def test_explicit_header_takes_precedence(self):
        result = SurfaceNegotiationService.infer_surface(
            headers={"X-Gimo-Surface": "cli", "User-Agent": "Claude Code"},
        )
        assert result == "cli"

    def test_infer_claude_from_user_agent(self):
        result = SurfaceNegotiationService.infer_surface(
            user_agent="Claude Code/1.2.3",
        )
        assert result == "claude_app"

    def test_infer_vscode_from_user_agent(self):
        result = SurfaceNegotiationService.infer_surface(
            user_agent="Visual Studio Code/1.90.0",
        )
        assert result == "vscode"

    def test_infer_cursor_from_user_agent(self):
        result = SurfaceNegotiationService.infer_surface(
            user_agent="Cursor/0.40",
        )
        assert result == "cursor"

    def test_infer_from_transport_stdio(self):
        result = SurfaceNegotiationService.infer_surface(transport="stdio")
        assert result == "cli"

    def test_infer_from_transport_websocket(self):
        result = SurfaceNegotiationService.infer_surface(transport="websocket")
        assert result == "web"

    def test_default_is_mcp_generic(self):
        result = SurfaceNegotiationService.infer_surface()
        assert result == "mcp_generic"
