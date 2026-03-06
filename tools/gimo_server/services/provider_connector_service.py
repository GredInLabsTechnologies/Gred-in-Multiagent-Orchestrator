from __future__ import annotations

import asyncio
import hashlib
import shutil
from asyncio.subprocess import PIPE
from typing import Any, Dict, Optional

from ..ops_models import CliDependencyInstallResponse, CliDependencyStatus


class ProviderConnectorService:
    """Connector-centric operations extracted from ProviderService."""

    _DEPENDENCIES: Dict[str, Dict[str, str]] = {
        "codex_cli": {
            "provider_type": "codex",
            "binary": "codex",
            "install_method": "npm",
            "install_command": "npm install -g @openai/codex",
            "version_arg": "--version",
        },
        "claude_cli": {
            "provider_type": "claude",
            "binary": "claude",
            "install_method": "npm",
            "install_command": "npm install -g @anthropic-ai/claude-code",
            "version_arg": "--version",
        },
        "gemini_cli": {
            "provider_type": "google",
            "binary": "gemini",
            "install_method": "npm",
            "install_command": "npm install -g @google/gemini-cli",
            "version_arg": "--version",
        },
    }
    _install_jobs: Dict[str, CliDependencyInstallResponse] = {}

    @staticmethod
    def _is_cli_installed(binary_name: str) -> bool:
        return shutil.which(binary_name) is not None

    @classmethod
    async def _resolve_cli_version(cls, binary_name: str, version_arg: str = "--version") -> Optional[str]:
        if not cls._is_cli_installed(binary_name):
            return None
        try:
            proc = await asyncio.create_subprocess_exec(binary_name, version_arg, stdout=PIPE, stderr=PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=4)
            output = (stdout or b"").decode("utf-8", errors="ignore").strip() or (stderr or b"").decode("utf-8", errors="ignore").strip()
            return output.splitlines()[0][:160] if output else None
        except Exception:
            return None

    @classmethod
    def _dependency_job_key(cls, dependency_id: str, job_id: str) -> str:
        return f"{dependency_id}:{job_id}"

    @classmethod
    def _set_dependency_job(
        cls,
        *,
        dependency_id: str,
        job_id: str,
        status: str,
        message: str,
        progress: Optional[float] = None,
        logs: Optional[list[str]] = None,
    ) -> CliDependencyInstallResponse:
        data = CliDependencyInstallResponse(
            status=status,  # type: ignore[arg-type]
            message=message,
            dependency_id=dependency_id,
            progress=progress,
            job_id=job_id,
            logs=list(logs or []),
        )
        cls._install_jobs[cls._dependency_job_key(dependency_id, job_id)] = data
        return data

    @classmethod
    async def _execute_dependency_install_job(cls, *, dependency_id: str, job_id: str) -> None:
        dep = cls._DEPENDENCIES.get(dependency_id)
        if not dep:
            cls._set_dependency_job(
                dependency_id=dependency_id,
                job_id=job_id,
                status="error",
                message=f"Unknown dependency: {dependency_id}",
                progress=1.0,
                logs=["Unknown dependency id"],
            )
            return

        install_command = str(dep.get("install_command") or "").strip()
        if not install_command:
            cls._set_dependency_job(
                dependency_id=dependency_id,
                job_id=job_id,
                status="error",
                message="No install command configured",
                progress=1.0,
                logs=["Install command is empty"],
            )
            return

        logs: list[str] = [f"$ {install_command}"]
        cls._set_dependency_job(
            dependency_id=dependency_id,
            job_id=job_id,
            status="running",
            message=f"Installing {dependency_id}...",
            progress=0.2,
            logs=logs,
        )
        try:
            proc = await asyncio.create_subprocess_shell(install_command, stdout=PIPE, stderr=PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            out = (stdout or b"").decode("utf-8", errors="ignore").strip()
            err = (stderr or b"").decode("utf-8", errors="ignore").strip()
            if out:
                logs.extend([line for line in out.splitlines()[:40] if line.strip()])
            if err:
                logs.extend([line for line in err.splitlines()[:40] if line.strip()])

            binary = str(dep.get("binary") or "")
            installed = cls._is_cli_installed(binary)
            if proc.returncode == 0 and installed:
                cls._set_dependency_job(
                    dependency_id=dependency_id,
                    job_id=job_id,
                    status="done",
                    message=f"{dependency_id} installed successfully",
                    progress=1.0,
                    logs=logs,
                )
            else:
                cls._set_dependency_job(
                    dependency_id=dependency_id,
                    job_id=job_id,
                    status="error",
                    message=f"Failed to install {dependency_id}",
                    progress=1.0,
                    logs=logs,
                )
        except Exception as exc:
            logs.append(f"install-error: {exc}")
            cls._set_dependency_job(
                dependency_id=dependency_id,
                job_id=job_id,
                status="error",
                message=f"Failed to install {dependency_id}",
                progress=1.0,
                logs=logs,
            )

    @classmethod
    async def list_cli_dependencies(cls) -> Dict[str, Any]:
        items: list[CliDependencyStatus] = []
        for dep_id, dep in cls._DEPENDENCIES.items():
            binary = str(dep.get("binary") or "")
            installed = cls._is_cli_installed(binary)
            version = await cls._resolve_cli_version(binary, str(dep.get("version_arg") or "--version"))
            items.append(
                CliDependencyStatus(
                    id=dep_id,
                    provider_type=str(dep.get("provider_type") or ""),
                    binary=binary,
                    installed=installed,
                    version=version,
                    installable=True,
                    install_method=str(dep.get("install_method") or "npm"),  # type: ignore[arg-type]
                    install_command=str(dep.get("install_command") or ""),
                    message="installed" if installed else "missing",
                )
            )
        return {"items": [i.model_dump() for i in items], "count": len(items)}

    @classmethod
    async def install_cli_dependency(cls, dependency_id: str) -> CliDependencyInstallResponse:
        dep_id = str(dependency_id or "").strip().lower()
        if dep_id not in cls._DEPENDENCIES:
            raise ValueError(f"Unknown dependency: {dependency_id}")
        job_id = hashlib.sha1(f"{dep_id}".encode("utf-8")).hexdigest()[:12]
        job = cls._set_dependency_job(
            dependency_id=dep_id,
            job_id=job_id,
            status="queued",
            message=f"Install queued for {dep_id}",
            progress=0.0,
            logs=[],
        )
        asyncio.create_task(cls._execute_dependency_install_job(dependency_id=dep_id, job_id=job_id))
        return job

    @classmethod
    def get_cli_dependency_install_job(cls, dependency_id: str, job_id: str) -> CliDependencyInstallResponse:
        key = cls._dependency_job_key(str(dependency_id or "").strip().lower(), str(job_id or "").strip())
        data = cls._install_jobs.get(key)
        if data:
            return data
        return CliDependencyInstallResponse(
            status="error",
            message="Install job not found",
            dependency_id=str(dependency_id or ""),
            job_id=str(job_id or ""),
            progress=1.0,
            logs=[],
        )

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
