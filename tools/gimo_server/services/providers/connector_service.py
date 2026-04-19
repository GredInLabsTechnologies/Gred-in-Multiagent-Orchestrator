from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
from asyncio.subprocess import PIPE
from typing import Any, Dict, List, Optional


async def _create_process(cmd: List[str], **kwargs) -> asyncio.subprocess.Process:
    """Create subprocess, using shell on Windows for npm .cmd shim compat."""
    if sys.platform == "win32":
        return await asyncio.create_subprocess_shell(" ".join(cmd), **kwargs)
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)

from ...ops_models import CliDependencyInstallResponse, CliDependencyInfo


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
    # Strong refs for fire-and-forget dependency install tasks (prevents premature GC).
    _install_bg_tasks: set[asyncio.Task] = set()

    @classmethod
    async def _run_install_preflight(cls, install_command: str) -> tuple[bool, list[str]]:
        """Commercial-grade preflight for CLI installation.

        We fail fast with explicit reasons instead of relying on implicit shell failures.
        """
        checks: list[str] = []

        npm_path = shutil.which("npm")
        node_path = shutil.which("node")
        if not npm_path:
            checks.append("missing:npm")
        else:
            checks.append(f"ok:npm:{npm_path}")
        if not node_path:
            checks.append("missing:node")
        else:
            checks.append(f"ok:node:{node_path}")

        # Validate npm registry connectivity (required for npm-based dependencies).
        if npm_path:
            try:
                ping = await _create_process(
                    ["npm", "ping", "--registry=https://registry.npmjs.org/"], stdout=PIPE, stderr=PIPE
                )
                _, ping_err = await asyncio.wait_for(ping.communicate(), timeout=15)
                if ping.returncode != 0:
                    detail = (ping_err or b"").decode("utf-8", errors="ignore").strip()
                    checks.append(f"fail:npm_registry:{detail or 'unreachable'}")
                else:
                    checks.append("ok:npm_registry")
            except Exception as exc:
                checks.append(f"fail:npm_registry:{exc}")

        # Validate writable npm global prefix for "npm install -g ...".
        if " -g " in f" {install_command} " and npm_path:
            try:
                proc = await _create_process(["npm", "config", "get", "prefix"], stdout=PIPE, stderr=PIPE)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
                prefix = (out or b"").decode("utf-8", errors="ignore").strip()
                if not prefix:
                    checks.append("fail:npm_prefix:empty")
                elif not os.path.isdir(prefix):
                    checks.append(f"fail:npm_prefix:not_found:{prefix}")
                elif not os.access(prefix, os.W_OK):
                    checks.append(f"fail:npm_prefix:not_writable:{prefix}")
                else:
                    checks.append(f"ok:npm_prefix:{prefix}")
            except Exception as exc:
                checks.append(f"fail:npm_prefix:{exc}")

        ok = not any(item.startswith(("missing:", "fail:")) for item in checks)
        return ok, checks

    @staticmethod
    def _is_cli_installed(binary_name: str) -> bool:
        return shutil.which(binary_name) is not None

    @classmethod
    async def _resolve_cli_version(cls, binary_name: str, version_arg: str = "--version") -> Optional[str]:
        if not cls._is_cli_installed(binary_name):
            return None
        try:
            proc = await _create_process([binary_name, version_arg], stdout=PIPE, stderr=PIPE)
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

        preflight_ok, preflight_logs = await cls._run_install_preflight(install_command)
        logs.extend(preflight_logs)
        if not preflight_ok:
            cls._set_dependency_job(
                dependency_id=dependency_id,
                job_id=job_id,
                status="error",
                message=f"Environment not ready for {dependency_id} installation",
                progress=1.0,
                logs=logs,
            )
            return

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
        items: list[CliDependencyInfo] = []
        for dep_id, dep in cls._DEPENDENCIES.items():
            binary = str(dep.get("binary") or "")
            installed = cls._is_cli_installed(binary)
            version = await cls._resolve_cli_version(binary, str(dep.get("version_arg") or "--version"))
            items.append(
                CliDependencyInfo(
                    id=dep_id,
                    provider_type=str(dep.get("provider_type") or ""),
                    binary=binary,
                    installed=installed,
                    version=version,
                    installable=True,
                    install_method=str(dep.get("install_method") or "npm"),
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
        job_id = hashlib.sha1(f"{dep_id}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]  # nosec B324
        job = cls._set_dependency_job(
            dependency_id=dep_id,
            job_id=job_id,
            status="queued",
            message=f"Install queued for {dep_id}",
            progress=0.0,
            logs=[],
        )
        _install_task = asyncio.create_task(
            cls._execute_dependency_install_job(dependency_id=dep_id, job_id=job_id)
        )
        cls._install_bg_tasks.add(_install_task)
        _install_task.add_done_callback(cls._install_bg_tasks.discard)
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

    # Known connector types (these are NOT provider_ids).
    _KNOWN_CONNECTORS = {"claude_code", "codex_cli", "gemini_cli", "openai_compat"}

    @classmethod
    def _resolve_connector(
        cls,
        provider_service_cls,
        connector_id: str,
        provider_id: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Resolve a caller-supplied ID to (connector_type, provider_id).

        If the caller sent a known connector_type, pass through.
        If not, treat it as a provider_id and resolve via ProviderConfig.
        This eliminates the abstraction leak where the CLI must know about
        connector types — it only needs to know provider names.
        """
        cid = str(connector_id).strip().lower()
        if cid in cls._KNOWN_CONNECTORS:
            return cid, provider_id

        # Treat as provider_id — resolve to openai_compat connector
        cfg = provider_service_cls.get_config()
        if cfg and cid in cfg.providers:
            return "openai_compat", cid

        # Check CLI account providers (e.g. "claude-account", "codex-account")
        cli_map = {
            "claude-account": "claude_code",
            "codex-account": "codex_cli",
            "gemini-account": "gemini_cli",
        }
        if cid in cli_map:
            return cli_map[cid], None

        # Last resort: if it looks like a provider type from metadata, assume openai_compat
        from .metadata import OPENAI_COMPAT_ADAPTER_TYPES
        if cid in OPENAI_COMPAT_ADAPTER_TYPES:
            return "openai_compat", provider_id

        raise ValueError(f"Unknown provider or connector: {connector_id}")

    @classmethod
    async def connector_health(
        cls,
        provider_service_cls,
        connector_id: str,
        provider_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        connector_id, provider_id = cls._resolve_connector(
            provider_service_cls, connector_id, provider_id,
        )

        if connector_id in {"claude_code", "codex_cli", "gemini_cli"}:
            binary = {
                "claude_code": "claude",
                "codex_cli": "codex",
                "gemini_cli": "gemini",
            }[connector_id]
            installed = cls._is_cli_installed(binary)
            # Verify the binary actually runs, not just exists on PATH
            version = await cls._resolve_cli_version(binary) if installed else None
            return {
                "id": connector_id,
                "healthy": installed and version is not None,
                "details": {"installed": installed, "binary": binary, "version": version},
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
