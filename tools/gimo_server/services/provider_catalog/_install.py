from __future__ import annotations

import asyncio
import hashlib
import shutil
from typing import Any, Dict, List, Tuple

from ...ops_models import (
    ProviderModelInstallResponse,
)
from ..providers.service import ProviderService
from ...security import audit_log
from ._base import ProviderCatalogBase


class InstallMixin:
    """Model installation/pull: install_model, get_install_job, execute_install_job, etc."""

    @classmethod
    async def install_model(cls, provider_type: str, model_id: str) -> ProviderModelInstallResponse:
        canonical = cls._canonical(provider_type)
        caps = ProviderService.capabilities_for(canonical)
        can_install = bool(caps.get("can_install", False))
        if not can_install:
            return ProviderModelInstallResponse(
                status="error",
                message=f"Provider '{canonical}' does not support local install.",
            )

        if canonical == "ollama_local":
            if shutil.which("ollama") is None:
                return ProviderModelInstallResponse(
                    status="error",
                    message="Ollama command not found in PATH.",
                )
            job_id = hashlib.sha1(f"ollama:{model_id}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]  # nosec B324
            cls._set_install_job(
                provider_type=canonical,
                model_id=model_id,
                job_id=job_id,
                status="queued",
                message=f"Install queued for model '{model_id}'.",
                progress=0.0,
            )
            audit_log(
                "OPS",
                "/ops/connectors/ollama_local/models/install/start",
                f"{canonical}:{model_id}:{job_id}",
                operation="EXECUTE",
                actor=cls._SYSTEM_ACTOR_INSTALL,
            )
            asyncio.create_task(
                cls._execute_install_job(
                    provider_type=canonical,
                    model_id=model_id,
                    job_id=job_id,
                    cmd=["ollama", "pull", model_id],
                )
            )
            result = ProviderModelInstallResponse(
                status="queued",
                message=f"Install queued for model '{model_id}'.",
                progress=0.0,
                job_id=job_id,
            )
            return result

        if canonical == "codex":
            job_id = hashlib.sha1(f"codex:{model_id}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]  # nosec B324
            cls._set_install_job(
                provider_type=canonical,
                model_id=model_id,
                job_id=job_id,
                status="done",
                message=(
                    f"Codex model activation prepared for '{model_id}'. "
                    "If your environment requires manual setup, run the vendor CLI setup flow."
                ),
                progress=1.0,
            )
            audit_log(
                "OPS",
                "/ops/connectors/codex/models/install/success",
                f"{canonical}:{model_id}:{job_id}",
                operation="EXECUTE",
                actor=cls._SYSTEM_ACTOR_INSTALL,
            )
            result = ProviderModelInstallResponse(
                status="done",
                message=(
                    f"Codex model activation prepared for '{model_id}'. "
                    "If your environment requires manual setup, run the vendor CLI setup flow."
                ),
                progress=1.0,
                job_id=job_id,
            )
            cls.invalidate_cache(provider_type=canonical, reason="installation_completed")
            return result

        return ProviderModelInstallResponse(
            status="error",
            message=f"Install flow is not implemented for provider '{canonical}'.",
        )

    @staticmethod
    async def _run_command_background(cmd: List[str]) -> Tuple[bool, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return True, stdout.decode("utf-8", errors="ignore").strip()[:500]
            err = stderr.decode("utf-8", errors="ignore").strip()[:500]
            return False, err or f"Command failed with return code {proc.returncode}"
        except Exception:
            return False, "Failed to execute installation command."

    @classmethod
    async def _execute_install_job(
        cls,
        *,
        provider_type: str,
        model_id: str,
        job_id: str,
        cmd: List[str],
    ) -> None:
        cls._set_install_job(
            provider_type=provider_type,
            model_id=model_id,
            job_id=job_id,
            status="running",
            message=f"Installing '{model_id}'...",
            progress=0.25,
        )
        ok, detail = await cls._run_command_background(cmd)
        if ok:
            cls._set_install_job(
                provider_type=provider_type,
                model_id=model_id,
                job_id=job_id,
                status="done",
                message=f"Model '{model_id}' installed successfully.",
                progress=1.0,
            )
            cls.invalidate_cache(provider_type=provider_type, reason="installation_completed")
            audit_log(
                "OPS",
                f"/ops/connectors/{provider_type}/models/install/success",
                f"{provider_type}:{model_id}:{job_id}",
                operation="EXECUTE",
                actor=cls._SYSTEM_ACTOR_INSTALL,
            )
            return

        cls._set_install_job(
            provider_type=provider_type,
            model_id=model_id,
            job_id=job_id,
            status="error",
            message=detail or f"Failed to install '{model_id}'.",
            progress=1.0,
        )
        audit_log(
            "OPS",
            f"/ops/connectors/{provider_type}/models/install/fail",
            f"{provider_type}:{model_id}:{job_id}",
            operation="EXECUTE",
            actor=cls._SYSTEM_ACTOR_INSTALL,
        )
