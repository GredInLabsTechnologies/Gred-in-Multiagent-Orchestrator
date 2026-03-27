from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from tools.gimo_server.app_mcp.resources import register_resources
from tools.gimo_server.app_mcp.tools import normalize_app_mcp_profile, register_tools
from tools.gimo_server.config import APP_MCP_PROFILE, APP_MCP_STREAMABLE_HTTP

logger = logging.getLogger("app_mcp.server")


def create_app_mcp(profile: str = "safe") -> FastMCP:
    normalized_profile = normalize_app_mcp_profile(profile)
    app_mcp = FastMCP("GIMO-App", dependencies=["httpx", "uvicorn", "fastapi"])
    register_tools(app_mcp, profile=normalized_profile)
    register_resources(app_mcp)
    return app_mcp


def _merge_middleware(*apps: Starlette) -> list:
    merged = []
    for app in apps:
        for middleware in getattr(app, "user_middleware", []):
            if middleware not in merged:
                merged.append(middleware)
    return merged


def build_official_app_facade(
    app_mcp: FastMCP,
    *,
    enable_streamable_http: bool = True,
) -> tuple[Starlette, AbstractAsyncContextManager[None] | None]:
    sse_app = app_mcp.sse_app()
    routes = list(sse_app.routes)
    middleware = _merge_middleware(sse_app)
    streamable_http_context = None

    if enable_streamable_http:
        streamable_http_app = app_mcp.streamable_http_app()
        routes.extend(streamable_http_app.routes)
        middleware = _merge_middleware(sse_app, streamable_http_app)
        streamable_http_context = app_mcp.session_manager.run()

    facade = Starlette(debug=sse_app.debug, routes=routes, middleware=middleware)
    return facade, streamable_http_context


def create_official_app_facade(
    *,
    profile: str | None = None,
    enable_streamable_http: bool | None = None,
) -> tuple[FastMCP, Starlette, AbstractAsyncContextManager[None] | None]:
    normalized_profile = normalize_app_mcp_profile(profile or APP_MCP_PROFILE)
    streamable_http = APP_MCP_STREAMABLE_HTTP if enable_streamable_http is None else enable_streamable_http
    app_mcp = create_app_mcp(normalized_profile)
    facade, streamable_http_context = build_official_app_facade(
        app_mcp,
        enable_streamable_http=streamable_http,
    )
    return app_mcp, facade, streamable_http_context


mcp = create_app_mcp(APP_MCP_PROFILE)
