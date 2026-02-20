from __future__ import annotations

import shutil
from typing import Any, Dict, Optional


class ProviderConnectorService:
    """Connector-centric operations extracted from ProviderService."""

    @staticmethod
    def _is_cli_installed(binary_name: str) -> bool:
        return shutil.which(binary_name) is not None

    @classmethod
    def list_connectors(cls, provider_service_cls) -> Dict[str, Any]:
        cfg = provider_service_cls.get_config()
        active_provider = cfg.active if cfg else None
        providers = sorted(cfg.providers) if cfg else []
        active_entry = cfg.providers.get(active_provider) if (cfg and active_provider in cfg.providers) else None
        active_model = active_entry.model_id or active_entry.model if active_entry else None

        items = [
            {
                "id": "claude_code",
                "type": "cli",
                "installed": cls._is_cli_installed("claude"),
                "configured": True,
                "healthy": cls._is_cli_installed("claude"),
                "default_model": "claude-sonnet",
            },
            {
                "id": "codex_cli",
                "type": "cli",
                "installed": cls._is_cli_installed("codex"),
                "configured": True,
                "healthy": cls._is_cli_installed("codex"),
                "default_model": "gpt-4o",
            },
            {
                "id": "gemini_cli",
                "type": "cli",
                "installed": cls._is_cli_installed("gemini"),
                "configured": True,
                "healthy": cls._is_cli_installed("gemini"),
                "default_model": "gemini-1.5-pro",
            },
            {
                "id": "openai_compat",
                "type": "api",
                "installed": True,
                "configured": bool(cfg and cfg.providers),
                "healthy": bool(cfg and cfg.providers),
                "active_provider": active_provider,
                "default_model": active_model,
                "providers": providers,
                "provider_capabilities": provider_service_cls.get_capability_matrix(),
            },
        ]

        if cfg and cfg.mcp_servers:
            for name, srv in cfg.mcp_servers.items():
                items.append(
                    {
                        "id": f"mcp_{name}",
                        "type": "mcp",
                        "installed": True,
                        "configured": srv.enabled,
                        "details": {"command": srv.command, "args": srv.args},
                    }
                )

        return {"items": items, "count": len(items)}

    @classmethod
    async def connector_health(
        cls,
        provider_service_cls,
        connector_id: str,
        provider_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        connector_id = str(connector_id).strip().lower()

        if connector_id in {"claude_code", "codex_cli", "gemini_cli"}:
            binary = {
                "claude_code": "claude",
                "codex_cli": "codex",
                "gemini_cli": "gemini",
            }[connector_id]
            installed = cls._is_cli_installed(binary)
            return {
                "id": connector_id,
                "healthy": installed,
                "details": {"installed": installed, "binary": binary},
            }

        if connector_id == "openai_compat":
            healthy = await (
                provider_service_cls.provider_health(provider_id)
                if provider_id
                else provider_service_cls.health_check()
            )
            cfg = provider_service_cls.get_config()
            return {
                "id": connector_id,
                "healthy": healthy,
                "details": {
                    "active_provider": provider_id or (cfg.active if cfg else None),
                    "providers": sorted(cfg.providers) if cfg else [],
                },
            }

        raise ValueError(f"Unknown connector: {connector_id}")
