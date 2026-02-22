from __future__ import annotations

import asyncio
import hashlib
import shutil
import time
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from ..ops_models import (
    NormalizedModelInfo,
    ProviderModelInstallResponse,
    ProviderModelsCatalogResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from .provider_service import ProviderService
from .provider_auth_service import ProviderAuthService
from ..security import audit_log


_OLLAMA_RECOMMENDED = [
    {"id": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B", "quality_tier": "balanced"},
    {"id": "llama3.1:8b", "label": "Llama 3.1 8B", "quality_tier": "balanced"},
]


class ProviderCatalogService:
    _CATALOG_CACHE: Dict[str, Tuple[float, ProviderModelsCatalogResponse]] = {}
    _INSTALL_JOBS: Dict[str, Dict[str, Any]] = {}
    _CATALOG_TTL_SECONDS: Dict[str, int] = {
        "ollama_local": 30,
        "openai": 300,
        "codex": 300,
        "groq": 300,
        "openrouter": 300,
        "custom_openai_compatible": 120,
    }

    @classmethod
    def _canonical(cls, provider_type: str) -> str:
        return ProviderService.normalize_provider_type(provider_type)

    @classmethod
    def _catalog_ttl_for(cls, provider_type: str) -> int:
        canonical = cls._canonical(provider_type)
        return int(cls._CATALOG_TTL_SECONDS.get(canonical, 120))

    @classmethod
    def _catalog_cache_key(
        cls,
        *,
        provider_type: str,
        payload: ProviderValidateRequest | None,
    ) -> str:
        canonical = cls._canonical(provider_type)
        base_url = (payload.base_url if payload else "") or ""
        org = (payload.org if payload else "") or ""
        account = (payload.account if payload else "") or ""
        has_api_key = bool((payload.api_key if payload else "") or "")
        return f"{canonical}|{base_url.strip()}|{org.strip()}|{account.strip()}|k={int(has_api_key)}"

    @classmethod
    def _resolve_payload_from_provider_config(cls, provider_type: str) -> ProviderValidateRequest | None:
        """Build non-persisted auth payload from current provider config when available.

        This allows GET catalog to return real remote models after provider is already configured,
        without requiring ad-hoc credential input on every request.
        """
        canonical = cls._canonical(provider_type)
        cfg = ProviderService.get_config()
        if not cfg:
            return None
        for _pid, entry in cfg.providers.items():
            et = cls._canonical(entry.provider_type or entry.type)
            if et != canonical:
                continue
            resolved_secret = ProviderAuthService.resolve_secret(entry)
            auth_mode = (entry.auth_mode or "").strip().lower()
            return ProviderValidateRequest(
                api_key=resolved_secret if auth_mode != "account" else None,
                base_url=entry.base_url,
                account=resolved_secret if auth_mode == "account" else None,
            )
        return None

    @classmethod
    def invalidate_cache(cls, provider_type: str | None = None, reason: str = "manual") -> int:
        _ = reason  # reserved for future logging/metrics
        if provider_type is None:
            n = len(cls._CATALOG_CACHE)
            cls._CATALOG_CACHE.clear()
            return n
        canonical = cls._canonical(provider_type)
        to_delete = [k for k in cls._CATALOG_CACHE.keys() if k.startswith(f"{canonical}|")]
        for k in to_delete:
            cls._CATALOG_CACHE.pop(k, None)
        return len(to_delete)

    @classmethod
    def _install_method_contract(cls, provider_type: str) -> str:
        raw = str(ProviderService.capabilities_for(provider_type).get("install_method") or "none")
        if raw in {"local_runtime", "cli", "command"}:
            return "command"
        if raw == "api":
            return "api"
        return "manual"

    @classmethod
    def _job_key(cls, provider_type: str, job_id: str) -> str:
        return f"{cls._canonical(provider_type)}:{job_id}"

    @classmethod
    def _set_install_job(
        cls,
        *,
        provider_type: str,
        model_id: str,
        job_id: str,
        status: str,
        message: str,
        progress: float | None = None,
    ) -> Dict[str, Any]:
        now = time.time()
        key = cls._job_key(provider_type, job_id)
        current = cls._INSTALL_JOBS.get(key, {})
        data = {
            "provider_type": cls._canonical(provider_type),
            "model_id": model_id,
            "job_id": job_id,
            "status": status,
            "message": message,
            "progress": progress,
            "created_at": current.get("created_at", now),
            "updated_at": now,
        }
        cls._INSTALL_JOBS[key] = data
        return data

    @classmethod
    def get_install_job(cls, provider_type: str, job_id: str) -> ProviderModelInstallResponse:
        key = cls._job_key(provider_type, job_id)
        data = cls._INSTALL_JOBS.get(key)
        if not data:
            return ProviderModelInstallResponse(
                status="error",
                message="Install job not found.",
                progress=0.0,
                job_id=job_id,
            )
        return ProviderModelInstallResponse(
            status=data["status"],
            message=data["message"],
            progress=data.get("progress"),
            job_id=data["job_id"],
        )

    @classmethod
    def _normalize_model(
        cls,
        *,
        model_id: str,
        label: str | None = None,
        installed: bool = False,
        downloadable: bool = False,
        context_window: int | None = None,
        size: str | None = None,
        quality_tier: str | None = None,
    ) -> NormalizedModelInfo:
        return NormalizedModelInfo(
            id=model_id,
            label=label or model_id,
            context_window=context_window,
            size=size,
            installed=installed,
            downloadable=downloadable,
            quality_tier=quality_tier,
        )

    @classmethod
    def _get_ollama_manifest_dir(cls) -> Optional[Path]:
        """Attempts to locate the Ollama models manifest directory."""
        # 1. Check environment variable (OLLAMA_MODELS usually points to /models)
        env_val = os.environ.get("OLLAMA_MODELS")
        if env_val:
            path = Path(env_val)
            if (path / "manifests").exists():
                return path / "manifests"
            if path.name == "models" and path.exists():
                 # Sometimes it points to the models folder itself
                 if (path / "manifests").exists():
                     return path / "manifests"
        
        # 2. Known custom path on this machine (discovered via research)
        special_path = Path("D:/Ollama/models/manifests")
        if special_path.exists():
            return special_path

        # 3. Default Windows/Local paths
        defaults = [
            Path(os.environ.get("USERPROFILE", "")) / ".ollama" / "models" / "manifests",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "models" / "manifests",
        ]
        for p in defaults:
            if p.exists():
                return p
        return None

    @classmethod
    def _ollama_list_from_disk(cls) -> List[NormalizedModelInfo]:
        """Scans the manifest directory for installed models without needing the daemon."""
        manifest_dir = cls._get_ollama_manifest_dir()
        if not manifest_dir:
            return []

        models: List[NormalizedModelInfo] = []
        try:
            # Structure: manifests/registry.ollama.ai/library/[model]/[tag]
            lib_path = manifest_dir / "registry.ollama.ai" / "library"
            if not lib_path.exists():
                return []
            
            for model_dir in lib_path.iterdir():
                if model_dir.is_dir():
                    model_name = model_dir.name
                    for tag_file in model_dir.iterdir():
                        if tag_file.is_file():
                            tag = tag_file.name
                            model_id = f"{model_name}:{tag}"
                            # We don't have metadata easily without parsing the JSON manifest,
                            # but for discovery, the ID is enough.
                            models.append(
                                cls._normalize_model(
                                    model_id=model_id,
                                    installed=True,
                                    downloadable=True
                                )
                            )
            return models
        except Exception:
            return []

    @classmethod
    async def _ollama_list_installed(cls) -> List[NormalizedModelInfo]:
        # 1. Try local API tags first (most accurate for running state)
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if 200 <= resp.status_code < 300:
                    data = resp.json() if resp.content else {}
                    models_data = data.get("models", []) if isinstance(data, dict) else []
                    models: List[NormalizedModelInfo] = []
                    for item in models_data:
                        model_id = str(item.get("name") or "").strip()
                        if not model_id:
                            continue
                        details = item.get("details") if isinstance(item.get("details"), dict) else {}
                        size = details.get("parameter_size") or item.get("size")
                        models.append(
                            cls._normalize_model(
                                model_id=model_id,
                                installed=True,
                                downloadable=True,
                                size=str(size) if size is not None else None,
                            )
                        )
                    if models:
                        return models
        except Exception:
            pass

        # 2. Robust Fallback: CLI parsing when API is not reachable.
        if shutil.which("ollama") is None:
            pass # Continue to disk scan
        else:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ollama",
                    "list",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _stderr = await proc.communicate()
                if proc.returncode == 0:
                    lines = stdout.decode("utf-8", errors="ignore").splitlines()
                    models: List[NormalizedModelInfo] = []
                    for idx, line in enumerate(lines):
                        if idx == 0 and "NAME" in line.upper():
                            continue
                        parts = [p for p in line.strip().split() if p]
                        if not parts:
                            continue
                        model_id = parts[0]
                        size = parts[2] if len(parts) >= 3 else None
                        models.append(
                            cls._normalize_model(
                                model_id=model_id,
                                installed=True,
                                downloadable=True,
                                size=size,
                            )
                        )
                    if models:
                        return models
            except Exception:
                pass

        # 3. Final Fallback: Direct Manifest Scanning (Truly Offline)
        return cls._ollama_list_from_disk()

    @classmethod
    async def ensure_ollama_ready(cls) -> bool:
        """Checks if Ollama is running; if not, attempts to start it in the background."""
        if await cls._ollama_health():
            return True

        # Service is down, attempt to wake it up
        if shutil.which("ollama") is None:
            return False

        try:
            # Start 'ollama serve' in background
            # Note: On Windows, we use CREATE_NO_WINDOW or similar via subproc flags if needed,
            # but a simple detached start usually works for Ollama's design.
            import subprocess
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                start_new_session=True
            )
            
            # Poll for readiness (max 30s)
            for _ in range(30):
                await asyncio.sleep(1.0)
                if await cls._ollama_health():
                    return True
            return False
        except Exception:
            return False

    @classmethod
    async def list_installed_models(cls, provider_type: str) -> List[NormalizedModelInfo]:
        canonical = cls._canonical(provider_type)
        if canonical == "ollama_local":
            return await cls._ollama_list_installed()
        cfg = ProviderService.get_config()
        if not cfg:
            return []
        models: List[NormalizedModelInfo] = []
        for _pid, entry in cfg.providers.items():
            et = cls._canonical(entry.provider_type or entry.type)
            if et != canonical:
                continue
            models.append(cls._normalize_model(model_id=entry.model, installed=True, downloadable=False))
        dedup: Dict[str, NormalizedModelInfo] = {m.id: m for m in models}
        return list(dedup.values())

    @classmethod
    async def list_available_models(
        cls, provider_type: str, payload: ProviderValidateRequest | None = None
    ) -> Tuple[List[NormalizedModelInfo], List[str]]:
        canonical = cls._canonical(provider_type)
        warnings: List[str] = []
        if canonical == "ollama_local":
            return [
                cls._normalize_model(
                    model_id=m["id"],
                    label=m.get("label"),
                    downloadable=True,
                    quality_tier=m.get("quality_tier"),
                )
                for m in _OLLAMA_RECOMMENDED
            ], warnings

        if canonical in {"openai", "codex", "groq", "openrouter", "custom_openai_compatible"}:
            auth = payload or ProviderValidateRequest()
            if not (auth.api_key or auth.account):
                warnings.append("Authentication is required to fetch remote model catalog.")
                return [], warnings

            remote = await cls._fetch_remote_models(canonical, auth)
            if remote:
                return remote, warnings
            warnings.append("Could not fetch remote models from provider API.")
            return [], warnings
        return [], warnings

    @classmethod
    async def _fetch_remote_models(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> List[NormalizedModelInfo]:
        base_url = (payload.base_url or "").strip()
        if not base_url:
            base_url = {
                "openai": "https://api.openai.com/v1",
                "codex": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "custom_openai_compatible": "",
            }.get(provider_type, "")
        if not base_url:
            return []

        headers = {"Content-Type": "application/json"}
        if payload.api_key:
            headers["Authorization"] = f"Bearer {payload.api_key}"
        elif payload.account:
            # Account mode is feature-gated at capabilities level; when enabled, we treat
            # provided account/session token as bearer credential for official endpoints.
            headers["Authorization"] = f"Bearer {payload.account}"
        if payload.org:
            headers["OpenAI-Organization"] = payload.org

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
                if resp.status_code < 200 or resp.status_code >= 300:
                    return []
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                out: List[NormalizedModelInfo] = []
                for item in items:
                    model_id = str(item.get("id") or "").strip()
                    if not model_id:
                        continue
                    out.append(cls._normalize_model(model_id=model_id, downloadable=False))
                return out
        except Exception:
            return []

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
            job_id = hashlib.sha1(f"ollama:{model_id}".encode("utf-8")).hexdigest()[:12]
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
                actor="system:provider_install",
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
            job_id = hashlib.sha1(f"codex:{model_id}".encode("utf-8")).hexdigest()[:12]
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
                actor="system:provider_install",
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
                actor="system:provider_install",
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
            actor="system:provider_install",
        )

    @classmethod
    def list_auth_modes(cls, provider_type: str) -> List[str]:
        canonical = cls._canonical(provider_type)
        return list(ProviderService.capabilities_for(canonical).get("auth_modes_supported") or [])

    @classmethod
    async def validate_credentials(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> ProviderValidateResponse:
        canonical = cls._canonical(provider_type)
        cls.invalidate_cache(provider_type=canonical, reason="manual_test_connection")
        warnings: List[str] = []

        if payload.account and str(payload.account).strip().lower().startswith("env:"):
            env_name = ProviderAuthService.parse_env_ref(payload.account)
            if env_name:
                payload = payload.model_copy(update={"account": (ProviderAuthService.resolve_env_expression(f"${{{env_name}}}") or "")})

        if canonical == "ollama_local":
            installed = shutil.which("ollama") is not None
            if not installed:
                response = ProviderValidateResponse(
                    valid=False,
                    health="down",
                    warnings=["Ollama command not found."],
                    error_actionable="Install Ollama and ensure it is available in PATH.",
                )
                ProviderService.record_validation_result(
                    provider_type=canonical,
                    valid=response.valid,
                    health=response.health,
                    effective_model=None,
                    error_actionable=response.error_actionable,
                    warnings=response.warnings,
                )
                return response
            ok = await cls._ollama_health()
            response = ProviderValidateResponse(
                valid=ok,
                health="ok" if ok else "degraded",
                warnings=[] if ok else ["Ollama runtime not reachable at local endpoint."],
                error_actionable=None if ok else "Start Ollama daemon and retry validation.",
            )
            ProviderService.record_validation_result(
                provider_type=canonical,
                valid=response.valid,
                health=response.health,
                effective_model=None,
                error_actionable=response.error_actionable,
                warnings=response.warnings,
            )
            return response

        supports_account = bool(ProviderService.capabilities_for(canonical).get("supports_account_mode", False))
        if payload.account and not supports_account:
            response = ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=["Account mode is not officially supported for this provider in current environment."],
                error_actionable="Use api_key mode for this provider.",
            )
            ProviderService.record_validation_result(
                provider_type=canonical,
                valid=response.valid,
                health=response.health,
                effective_model=None,
                error_actionable=response.error_actionable,
                warnings=response.warnings,
            )
            return response

        if not payload.api_key and not payload.account:
            response = ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=["Missing credentials payload."],
                error_actionable="Provide api_key or account according to selected auth mode.",
            )
            ProviderService.record_validation_result(
                provider_type=canonical,
                valid=response.valid,
                health=response.health,
                effective_model=None,
                error_actionable=response.error_actionable,
                warnings=response.warnings,
            )
            return response

        remote = await cls._fetch_remote_models(canonical, payload)
        if remote:
            response = ProviderValidateResponse(
                valid=True,
                health="ok",
                effective_model=remote[0].id,
                warnings=warnings,
            )
            ProviderService.record_validation_result(
                provider_type=canonical,
                valid=response.valid,
                health=response.health,
                effective_model=response.effective_model,
                error_actionable=response.error_actionable,
                warnings=response.warnings,
            )
            return response

        response = ProviderValidateResponse(
            valid=False,
            health="degraded",
            warnings=["Remote API reachable check failed or returned empty catalog."],
            error_actionable="Verify base_url, api_key/org and provider account permissions.",
        )
        ProviderService.record_validation_result(
            provider_type=canonical,
            valid=response.valid,
            health=response.health,
            effective_model=None,
            error_actionable=response.error_actionable,
            warnings=response.warnings,
        )
        return response

    @classmethod
    async def _ollama_health(cls) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                return 200 <= resp.status_code < 300
        except Exception:
            return False

    @classmethod
    async def get_catalog(
        cls, provider_type: str, payload: ProviderValidateRequest | None = None
    ) -> ProviderModelsCatalogResponse:
        canonical = cls._canonical(provider_type)
        effective_payload = payload or cls._resolve_payload_from_provider_config(canonical)
        cache_key = cls._catalog_cache_key(provider_type=canonical, payload=effective_payload)
        now = time.time()
        cached = cls._CATALOG_CACHE.get(cache_key)
        if cached:
            expires_at, response = cached
            if now < expires_at:
                return response
            cls._CATALOG_CACHE.pop(cache_key, None)

        installed = await cls.list_installed_models(canonical)
        available, warnings = await cls.list_available_models(canonical, payload=effective_payload)

        installed_ids = {m.id for m in installed}
        available_ids = {m.id for m in available}
        available = [m.model_copy(update={"installed": m.id in installed_ids}) for m in available]

        rec_raw = _OLLAMA_RECOMMENDED if canonical == "ollama_local" else []
        recommended = [
            cls._normalize_model(
                model_id=r["id"],
                label=r.get("label"),
                downloadable=(canonical == "ollama_local"),
                installed=r["id"] in installed_ids,
                quality_tier=r.get("quality_tier"),
                context_window=r.get("context_window"),
            )
            for r in rec_raw
            if r["id"] in available_ids or canonical == "ollama_local"
        ]

        response = ProviderModelsCatalogResponse(
            provider_type=canonical,  # type: ignore[arg-type]
            installed_models=installed,
            available_models=available,
            recommended_models=recommended,
            can_install=bool(ProviderService.capabilities_for(canonical).get("can_install", False)),
            install_method=cls._install_method_contract(canonical),  # type: ignore[arg-type]
            auth_modes_supported=cls.list_auth_modes(canonical),
            warnings=warnings,
        )
        ttl = cls._catalog_ttl_for(canonical)
        cls._CATALOG_CACHE[cache_key] = (now + ttl, response)
        return response
