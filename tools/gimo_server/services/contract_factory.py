"""ContractFactory: Builds immutable GimoContract from request context.

Reconciles the 5 sources of truth:
1. Auth (from verified token)
2. Provider (from provider.json + active binding)
3. Schema (from Pydantic AgentRole)
4. Workspace (from header or default)
5. License (from LicenseGuard)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from tools.gimo_server.config import get_settings
from tools.gimo_server.models.contract import (
    DEFAULT_VALID_SCOPES,
    GimoContract,
    extract_valid_roles,
)
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.providers.service import ProviderService

logger = logging.getLogger("orchestrator.contract_factory")


class ContractFactory:
    """Factory for building immutable GimoContract instances."""

    @staticmethod
    def build(auth: AuthContext, request: Request) -> GimoContract:
        """Build a GimoContract from request context.

        Args:
            auth: Validated authentication context (from verify_token)
            request: FastAPI request object

        Returns:
            Immutable GimoContract

        Raises:
            HTTPException: If provider is not configured or workspace is invalid
        """
        settings = get_settings()

        # 1. IDENTITY — Already validated by verify_token
        caller_role = auth.role

        # Agents NEVER get admin privileges (defense in depth)
        # Even if a plan is created by admin, the executing agent operates at t1
        agent_trust_ceiling = "t1"

        # 2. PROVIDER — Resolve ONCE, fail fast if not configured
        cfg = ProviderService.get_config()
        if not cfg or not cfg.active:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No active provider configured. "
                    "Set ANTHROPIC_API_KEY or run: gimo providers setup"
                ),
            )

        provider_entry = cfg.providers.get(cfg.active)
        if not provider_entry:
            raise HTTPException(
                status_code=500,
                detail=f"Active provider '{cfg.active}' not found in providers map",
            )

        provider_id = cfg.active
        model_id = provider_entry.model

        # 3. WORKSPACE — Explicit from header, query param, or default
        # Priority: X-Gimo-Workspace header > workspace query param > base_dir
        workspace_str = (
            request.headers.get("X-Gimo-Workspace")
            or request.query_params.get("workspace")
            or str(settings.base_dir)
        )

        try:
            workspace_root = Path(workspace_str).resolve()
        except (ValueError, OSError, TypeError) as exc:
            # Catch path resolution errors (invalid chars, permissions, type issues)
            raise HTTPException(
                status_code=400,
                detail=f"Invalid workspace path: {workspace_str} ({exc})",
            ) from exc

        if not workspace_root.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Workspace does not exist: {workspace_root}",
            )

        # 4. SCHEMA CONSTRAINTS — Extract from Pydantic (SINGLE SOURCE OF TRUTH)
        valid_roles = extract_valid_roles()
        valid_scopes = DEFAULT_VALID_SCOPES

        # 5. LICENSE PLAN — From LicenseGuard set at startup
        license_guard = getattr(request.app.state, "license_guard", None)
        if license_guard:
            # LicenseGuard has a _last_status attribute with plan info
            last_status = getattr(license_guard, "_last_status", None)
            license_plan = str(getattr(last_status, "plan", "unknown"))
        else:
            license_plan = "unknown"

        # 6. SAGP SURFACE — Detect from X-Gimo-Surface header
        surface = None
        surface_header = request.headers.get("X-Gimo-Surface", "").strip()
        if surface_header:
            from tools.gimo_server.models.surface import SurfaceIdentity
            surface = SurfaceIdentity(
                surface_type=surface_header if surface_header in (
                    "claude_app", "vscode", "cursor", "cli", "tui",
                    "web", "chatgpt_app", "mcp_generic", "agent_sdk",
                ) else "mcp_generic",
                surface_name=request.headers.get("User-Agent", surface_header),
            )

        contract = GimoContract(
            caller_role=caller_role,
            agent_trust_ceiling=agent_trust_ceiling,
            provider_id=provider_id,
            model_id=model_id,
            workspace_root=workspace_root,
            valid_roles=valid_roles,
            valid_scopes=valid_scopes,
            created_at=datetime.now(timezone.utc),
            license_plan=license_plan,
            surface=surface,
        )

        logger.debug(
            "Built GimoContract: role=%s, provider=%s, model=%s, workspace=%s",
            caller_role,
            provider_id,
            model_id,
            workspace_root,
        )

        return contract
