from __future__ import annotations

import asyncio
import hashlib
import json as _json
import shutil
import subprocess
import time
import os
import sys
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
from .ops_service import OpsService
from .provider_catalog_ollama_helpers import (
    ensure_ollama_ready as _ensure_ollama_ready_helper,
    ollama_health as _ollama_health_helper,
    ollama_list_installed as _ollama_list_installed_helper,
)
from .provider_metadata import OPENAI_COMPAT_CATALOG_TYPES, REMOTE_MODELS_BASE_URLS
from ..security import audit_log


# Recommended Ollama models for local agentic code workloads.
# Sorted by: coding capability > tool-use support > VRAM requirements.
_OLLAMA_RECOMMENDED = [
    # ── Top coding models ─────────────────────────────────────────────────────
    {"id": "qwen2.5-coder:32b",       "label": "Qwen 2.5 Coder 32B",      "quality_tier": "premium"},
    {"id": "qwen2.5-coder:14b",       "label": "Qwen 2.5 Coder 14B",      "quality_tier": "balanced"},
    {"id": "qwen2.5-coder:7b",        "label": "Qwen 2.5 Coder 7B",       "quality_tier": "balanced"},
    {"id": "qwen2.5-coder:1.5b",      "label": "Qwen 2.5 Coder 1.5B",     "quality_tier": "fast"},
    {"id": "devstral:24b",            "label": "Devstral 24B",             "quality_tier": "premium"},
    {"id": "deepseek-coder-v2:16b",   "label": "DeepSeek Coder V2 16B",   "quality_tier": "balanced"},
    # ── General models with strong tool-calling ────────────────────────────────
    {"id": "llama3.1:70b",            "label": "Llama 3.1 70B",           "quality_tier": "premium"},
    {"id": "llama3.1:8b",             "label": "Llama 3.1 8B",            "quality_tier": "balanced"},
    {"id": "llama3.2:3b",             "label": "Llama 3.2 3B",            "quality_tier": "fast"},
    {"id": "granite3.1-dense:8b",     "label": "Granite 3.1 8B",          "quality_tier": "balanced"},
    {"id": "granite3.1-dense:2b",     "label": "Granite 3.1 2B",          "quality_tier": "fast"},
    {"id": "phi4:14b",                "label": "Phi-4 14B",               "quality_tier": "balanced"},
    {"id": "mistral-nemo:12b",        "label": "Mistral Nemo 12B",        "quality_tier": "balanced"},
    {"id": "mistral:7b-instruct",     "label": "Mistral 7B Instruct",     "quality_tier": "balanced"},
]

# Default curated model fallback lists — used when the provider API is unreachable
# or credentials are not yet configured. Ordered by: coding quality desc.
_DEFAULT_PROVIDER_MODELS: Dict[str, List[Dict[str, str]]] = {
    # ── Paid-only providers ────────────────────────────────────────────────────
    "openai": [
        {"id": "gpt-4o",           "label": "GPT-4o"},
        {"id": "gpt-4o-mini",      "label": "GPT-4o mini"},
        {"id": "o3",               "label": "o3"},
        {"id": "o4-mini",          "label": "o4-mini"},
    ],
    "codex": [
        {"id": "o4-mini",          "label": "o4-mini (default)"},
        {"id": "o3",               "label": "o3"},
        {"id": "gpt-4o",           "label": "GPT-4o"},
        {"id": "gpt-4o-mini",      "label": "GPT-4o mini"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-5",          "label": "Claude Sonnet 4.5"},
        {"id": "claude-opus-4-5",            "label": "Claude Opus 4.5"},
        {"id": "claude-haiku-4-5-20251001",  "label": "Claude Haiku 4.5"},
        {"id": "claude-3-7-sonnet-latest",   "label": "Claude 3.7 Sonnet"},
        {"id": "claude-3-5-haiku-latest",    "label": "Claude 3.5 Haiku"},
    ],
    "claude": [
        {"id": "claude-sonnet-4-5",          "label": "Claude Sonnet 4.5"},
        {"id": "claude-opus-4-5",            "label": "Claude Opus 4.5"},
        {"id": "claude-haiku-4-5-20251001",  "label": "Claude Haiku 4.5"},
        {"id": "claude-3-7-sonnet-latest",   "label": "Claude 3.7 Sonnet"},
        {"id": "claude-3-5-haiku-latest",    "label": "Claude 3.5 Haiku"},
    ],
    # ── Free-tier providers (coding-focused) ───────────────────────────────────
    "google": [
        # Free tier via Google AI Studio (generous RPM/TPD limits)
        {"id": "gemini-2.0-flash",       "label": "Gemini 2.0 Flash (free)"},
        {"id": "gemini-2.0-flash-lite",  "label": "Gemini 2.0 Flash Lite (free)"},
        {"id": "gemini-1.5-flash",       "label": "Gemini 1.5 Flash (free)"},
        {"id": "gemini-1.5-flash-8b",    "label": "Gemini 1.5 Flash 8B (free)"},
        {"id": "gemini-1.5-pro",         "label": "Gemini 1.5 Pro (2 RPM free)"},
    ],
    "mistral": [
        # Free on La Plateforme; codestral is the specialized coder
        {"id": "codestral-latest",       "label": "Codestral (free, code specialist)"},
        {"id": "open-codestral-mamba",   "label": "Codestral Mamba (free)"},
        {"id": "open-mistral-nemo",      "label": "Mistral Nemo (free, 128K)"},
        {"id": "open-mixtral-8x22b",     "label": "Mixtral 8x22B (free)"},
        {"id": "open-mixtral-8x7b",      "label": "Mixtral 8x7B (free)"},
        {"id": "mistral-small-latest",   "label": "Mistral Small"},
        {"id": "mistral-large-latest",   "label": "Mistral Large"},
    ],
    "cohere": [
        # Trial key: 20 calls/min, 1K calls/month; Command-R has best tool-use
        {"id": "command-r7b-12-2024",  "label": "Command R7B (free trial)"},
        {"id": "command-r",            "label": "Command R (free trial)"},
        {"id": "command-r-plus",       "label": "Command R+"},
    ],
    "deepseek": [
        # Very cheap ($0.14/1M); free credits on signup; V3 supports tool calling
        {"id": "deepseek-chat",      "label": "DeepSeek V3 (code + tools)"},
        {"id": "deepseek-reasoner",  "label": "DeepSeek R1 (reasoning, no tools)"},
    ],
    "qwen": [
        # DashScope free monthly quota; coder models are best for GIMO
        {"id": "qwen2.5-coder-32b-instruct",  "label": "Qwen 2.5 Coder 32B (free quota)"},
        {"id": "qwen2.5-coder-7b-instruct",   "label": "Qwen 2.5 Coder 7B (free quota)"},
        {"id": "qwq-32b",                      "label": "QwQ 32B (reasoning)"},
        {"id": "qwen-turbo",                   "label": "Qwen Turbo (fast, cheap)"},
        {"id": "qwen-plus",                    "label": "Qwen Plus"},
        {"id": "qwen-max",                     "label": "Qwen Max"},
    ],
    "groq": [
        # Generous free tier: ~30 RPM, 6K TPM per model; ultra-fast inference
        {"id": "llama-3.3-70b-versatile",        "label": "Llama 3.3 70B (free)"},
        {"id": "llama-3.1-70b-versatile",        "label": "Llama 3.1 70B (free)"},
        {"id": "llama-3.1-8b-instant",           "label": "Llama 3.1 8B Instant (free, fast)"},
        {"id": "deepseek-r1-distill-llama-70b",  "label": "DeepSeek R1 Distill 70B (free)"},
        {"id": "mixtral-8x7b-32768",             "label": "Mixtral 8x7B (free)"},
        {"id": "gemma2-9b-it",                   "label": "Gemma 2 9B (free)"},
    ],
    "openrouter": [
        # Free `:free` routing — no API cost; best free coding models for agentic use
        {"id": "qwen/qwen-2.5-coder-32b-instruct:free",    "label": "Qwen 2.5 Coder 32B (free)"},
        {"id": "deepseek/deepseek-v3:free",                "label": "DeepSeek V3 (free)"},
        {"id": "meta-llama/llama-3.3-70b-instruct:free",   "label": "Llama 3.3 70B (free)"},
        {"id": "google/gemini-2.0-flash-exp:free",         "label": "Gemini 2.0 Flash Exp (free)"},
        {"id": "deepseek/deepseek-r1:free",                "label": "DeepSeek R1 (free, reasoning)"},
        {"id": "mistralai/mistral-nemo:free",              "label": "Mistral Nemo (free)"},
        {"id": "qwen/qwq-32b:free",                        "label": "QwQ 32B (free, reasoning)"},
        {"id": "meta-llama/llama-3.1-8b-instruct:free",    "label": "Llama 3.1 8B (free, fast)"},
        {"id": "openrouter/auto",                          "label": "OpenRouter Auto"},
    ],
    "together": [
        # $5 signup credits; serverless pay-per-use; near-free for light agentic work
        {"id": "Qwen/Qwen2.5-Coder-32B-Instruct",               "label": "Qwen 2.5 Coder 32B"},
        {"id": "deepseek-ai/DeepSeek-V3",                        "label": "DeepSeek V3"},
        {"id": "meta-llama/Meta-Llama-3.3-70B-Instruct-Turbo",  "label": "Llama 3.3 70B Turbo"},
        {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",  "label": "Llama 3.1 70B Turbo"},
        {"id": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",   "label": "Llama 3.1 8B Turbo"},
        {"id": "mistralai/Mixtral-8x22B-Instruct-v0.1",         "label": "Mixtral 8x22B"},
        {"id": "Qwen/Qwen2.5-72B-Instruct-Turbo",               "label": "Qwen 2.5 72B Turbo"},
    ],
    "fireworks": [
        # $1 signup credit; OpenAI-compat; best for fast agentic coding
        {"id": "accounts/fireworks/models/qwen2p5-coder-32b-instruct",  "label": "Qwen 2.5 Coder 32B"},
        {"id": "accounts/fireworks/models/deepseek-v3",                 "label": "DeepSeek V3"},
        {"id": "accounts/fireworks/models/llama-v3p3-70b-instruct",     "label": "Llama 3.3 70B"},
        {"id": "accounts/fireworks/models/llama-v3p1-70b-instruct",     "label": "Llama 3.1 70B"},
        {"id": "accounts/fireworks/models/llama-v3p1-8b-instruct",      "label": "Llama 3.1 8B (fast)"},
        {"id": "accounts/fireworks/models/mixtral-8x7b-instruct",       "label": "Mixtral 8x7B"},
    ],
    "huggingface": [
        # Free HF_TOKEN (rate-limited); HF Inference Router (OpenAI-compat)
        {"id": "Qwen/Qwen2.5-Coder-32B-Instruct",      "label": "Qwen 2.5 Coder 32B (free)"},
        {"id": "meta-llama/Llama-3.3-70B-Instruct",    "label": "Llama 3.3 70B (free)"},
        {"id": "meta-llama/Llama-3.1-70B-Instruct",    "label": "Llama 3.1 70B (free)"},
        {"id": "meta-llama/Llama-3.1-8B-Instruct",     "label": "Llama 3.1 8B (free, fast)"},
        {"id": "mistralai/Mistral-Nemo-Instruct-2407",  "label": "Mistral Nemo 12B (free)"},
        {"id": "microsoft/Phi-3.5-mini-instruct",       "label": "Phi-3.5 Mini (free, fast)"},
    ],
    "zai": [
        # glm-4-flash is truly free (10M tokens/month); codegeex-4 is the coding specialist
        {"id": "glm-4-flash",   "label": "GLM-4 Flash (free, 128K)"},
        {"id": "codegeex-4",    "label": "CodeGeeX-4 (free, code specialist)"},
        {"id": "glm-4-air",     "label": "GLM-4 Air"},
        {"id": "glm-4.6",       "label": "GLM-4.6"},
    ],
    "moonshot": [
        # Monthly free quota; specialized in long-context code analysis
        {"id": "moonshot-v1-128k",  "label": "Moonshot v1 128K (long-context code)"},
        {"id": "moonshot-v1-32k",   "label": "Moonshot v1 32K"},
        {"id": "moonshot-v1-8k",    "label": "Moonshot v1 8K (fast)"},
    ],
    "minimax": [
        {"id": "minimax-m1",      "label": "MiniMax M1 (1M ctx, reasoning)"},
        {"id": "abab6.5s-chat",   "label": "ABAB 6.5S (245K ctx, fast)"},
    ],
    "01-ai": [
        {"id": "yi-large",        "label": "Yi Large (32K, tools)"},
        {"id": "yi-large-turbo",  "label": "Yi Large Turbo (fast)"},
        {"id": "yi-medium",       "label": "Yi Medium"},
    ],
    # ── Infrastructure providers (self-hosted / cloud deployment) ──────────────
    "baidu":      [{"id": "ernie-4.0",         "label": "ERNIE 4.0"}],
    "tencent":    [{"id": "hunyuan-turbo",      "label": "Hunyuan Turbo"}],
    "bytedance":  [{"id": "doubao-1-5-pro",     "label": "Doubao 1.5 Pro"}],
    "iflytek":    [{"id": "spark-max",          "label": "Spark Max"}],
    "replicate":  [{"id": "meta/meta-llama-3-70b-instruct", "label": "Llama 3 70B (Replicate)"}],
    "azure-openai": [{"id": "gpt-4o",           "label": "GPT-4o (deployment)"}],
    "aws-bedrock":  [{"id": "anthropic.claude-3-5-sonnet-20241022-v2:0", "label": "Claude 3.5 Sonnet (Bedrock)"}],
    "vertex-ai":    [{"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (Vertex)"}],
    "vllm":         [{"id": "meta-llama/Llama-3.1-8B-Instruct",  "label": "Llama 3.1 8B Instruct"}],
    "llama-cpp":    [{"id": "qwen2.5-coder-7b-instruct-q4_k_m",  "label": "Qwen 2.5 Coder 7B Q4_K_M"}],
    "tgi":          [{"id": "meta-llama/Llama-3.1-8B-Instruct",  "label": "Llama 3.1 8B Instruct"}],
}



def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_mock_token(value: str | None) -> bool:
    raw = str(value or "").strip().lower()
    return raw.startswith("mock:") or raw.startswith("mock_") or raw == "mock"


def _mock_mode_enabled(payload: ProviderValidateRequest | None = None) -> bool:
    if _is_truthy_env(os.environ.get("ORCH_PROVIDER_MOCK_MODE")):
        return True
    if payload and (_is_mock_token(payload.api_key) or _is_mock_token(payload.account)):
        return True
    return False


def _run_sync(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a CLI command synchronously; uses shell=True on Windows for .cmd shim compat."""
    try:
        cmd = " ".join(args) if sys.platform == "win32" else args
        clean_env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE")}
        proc = subprocess.Popen(
            cmd, shell=(sys.platform == "win32"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=clean_env,  # remove nested-session guard so claude/codex CLIs work
        )
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, (out or b"").decode("utf-8", errors="replace").strip()
    except Exception as exc:
        return -1, str(exc)


async def _fetch_claude_cli_models() -> List[NormalizedModelInfo]:
    """Discover Claude models dynamically via `claude api get /v1/models`.

    Runs from the server process (no CLAUDECODE guard) using run_in_executor
    so it doesn't block the event loop.
    """
    loop = asyncio.get_event_loop()
    try:
        rc, output = await asyncio.wait_for(
            loop.run_in_executor(None, _run_sync, ["claude", "api", "get", "/v1/models"]),
            timeout=12.0,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return []
    except Exception:
        return []

    if rc != 0 or not output:
        return []

    try:
        data = _json.loads(output)
        items = data.get("data", []) if isinstance(data, dict) else []
        models: List[NormalizedModelInfo] = []
        for item in items:
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            display_name = str(item.get("display_name") or item.get("name") or model_id)
            context_window = item.get("context_window") or None
            models.append(NormalizedModelInfo(
                id=model_id,
                label=display_name,
                context_window=context_window,
                installed=False,
                downloadable=False,
            ))
        return models
    except Exception:
        return []


def _fallback_models_for(provider_type: str) -> List[NormalizedModelInfo]:
    return [
        ProviderCatalogService._normalize_model(
            model_id=m["id"],
            label=m.get("label"),
            downloadable=False,
        )
        for m in _DEFAULT_PROVIDER_MODELS.get(provider_type, [])
    ]


class ProviderCatalogService:
    """Lleva el registro de proveedores LLM, modelos e integracion."""
    _CATALOG_CACHE: Dict[str, Tuple[float, ProviderModelsCatalogResponse]] = {}
    _INSTALL_JOBS: Dict[str, Dict[str, Any]] = {}
    _CATALOG_TTL_SECONDS: Dict[str, int] = {
        "ollama_local": 30,
        "openai": 300,
        "codex": 300,
        "claude": 300,
        "anthropic": 300,
        "groq": 300,
        "openrouter": 300,
        "custom_openai_compatible": 120,
    }
    _SYSTEM_ACTOR_INSTALL = "system:provider_install"

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
        description: str | None = None,
        capabilities: List[str] | None = None,
        weakness: str | None = None,
    ) -> NormalizedModelInfo:
        return NormalizedModelInfo(
            id=model_id,
            label=label or model_id,
            context_window=context_window,
            size=size,
            installed=installed,
            downloadable=downloadable,
            quality_tier=quality_tier,
            description=description,
            capabilities=list(capabilities or []),
            weakness=weakness,
        )

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    @classmethod
    def _infer_capabilities(cls, model_id: str, description: str | None = None) -> List[str]:
        bag = f"{model_id} {description or ''}".lower()
        caps: List[str] = []
        if any(k in bag for k in ["code", "coder", "codex", "program", "software"]):
            caps.append("code")
        if any(k in bag for k in ["reason", "thinking", "logic", "math"]):
            caps.append("reasoning")
        if any(k in bag for k in ["tool", "function", "agent"]):
            caps.append("tools")
        if any(k in bag for k in ["vision", "image", "multimodal"]):
            caps.append("multimodal")
        return caps

    @classmethod
    def _build_prior_scores(
        cls,
        *,
        model_id: str,
        capabilities: List[str],
        context_window: int | None,
    ) -> Dict[str, float]:
        priors: Dict[str, float] = {
            "coding": 0.45,
            "reasoning": 0.45,
            "tools": 0.35,
        }
        caps = set(capabilities or [])
        if "code" in caps:
            priors["coding"] = max(priors["coding"], 0.85)
        if "reasoning" in caps:
            priors["reasoning"] = max(priors["reasoning"], 0.8)
        if "tools" in caps:
            priors["tools"] = max(priors["tools"], 0.75)
        if context_window and context_window >= 128000:
            priors["reasoning"] = max(priors["reasoning"], 0.75)
        raw = model_id.lower()
        if "codex" in raw or "coder" in raw:
            priors["coding"] = max(priors["coding"], 0.9)
        return priors

    @classmethod
    def _infer_weakness(cls, model_id: str) -> str | None:
        raw = model_id.lower()
        if any(k in raw for k in ["opus", "gpt-5", "o1", "r1", "70b"]):
            return "Coste alto"
        return None

    @classmethod
    async def _ollama_list_installed(cls) -> List[NormalizedModelInfo]:
        return await _ollama_list_installed_helper(cls._normalize_model)

    @classmethod
    async def ensure_ollama_ready(cls) -> bool:
        return await _ensure_ollama_ready_helper()

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

        if _mock_mode_enabled(payload):
            return cls._handle_mock_mode_catalog(canonical)

        if canonical == "ollama_local":
            return [
                cls._normalize_model(
                    model_id=m["id"], label=m.get("label"),
                    downloadable=True, quality_tier=m.get("quality_tier"),
                ) for m in _OLLAMA_RECOMMENDED
            ], warnings

        # Claude account mode: try dynamic discovery via `claude api get /v1/models`.
        # Falls back to curated defaults if the CLI is unavailable or not authenticated.
        if canonical == "claude" and not (payload and payload.api_key):
            if shutil.which("claude"):
                live = await _fetch_claude_cli_models()
                if live:
                    return live, warnings
            return _fallback_models_for(canonical), warnings

        if canonical in {"replicate", "anthropic", "google", "mistral", "cohere"}:
            warnings.append("This provider may not expose a universal /models endpoint. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        # Codex uses CLI account sessions — remote /models is not reachable via account token.
        if canonical == "codex" and not (payload and payload.api_key):
            return _fallback_models_for(canonical), warnings

        if canonical in {"vllm", "llama-cpp", "tgi", "azure-openai", "aws-bedrock", "vertex-ai"}:
            remote = await cls._fetch_remote_if_auth(canonical, payload)
            if remote:
                return remote, warnings
            warnings.append("This provider needs endpoint/credentials configuration to discover runtime models dynamically. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        if canonical in OPENAI_COMPAT_CATALOG_TYPES:
            return await cls._handle_openai_compatible_catalog(canonical, payload, warnings)
            
        return [], warnings

    @classmethod
    async def _fetch_remote_if_auth(cls, canonical: str, payload: ProviderValidateRequest | None) -> List[NormalizedModelInfo]:
        auth = payload or ProviderValidateRequest()
        if (auth.base_url and (auth.api_key or auth.account)) or auth.base_url:
            return await cls._fetch_remote_models(canonical, auth)
        return []

    @classmethod
    def _handle_mock_mode_catalog(cls, canonical: str) -> Tuple[List[NormalizedModelInfo], List[str]]:
        if canonical == "ollama_local":
            return [
                cls._normalize_model(
                    model_id=m["id"], label=m.get("label"),
                    downloadable=True, quality_tier=m.get("quality_tier"),
                ) for m in _OLLAMA_RECOMMENDED
            ], ["Mock mode enabled: returning deterministic catalog without network."]
        mock_models = _fallback_models_for(canonical)
        if mock_models:
            return mock_models, ["Mock mode enabled: returning deterministic catalog without network."]
        return [cls._normalize_model(model_id=f"{canonical}-mock-model", label=f"{canonical} mock model")], [
            "Mock mode enabled: using synthetic model catalog for provider."
        ]

    @classmethod
    async def _handle_openai_compatible_catalog(cls, canonical: str, payload: ProviderValidateRequest | None, warnings: List[str]) -> Tuple[List[NormalizedModelInfo], List[str]]:
        auth = payload or ProviderValidateRequest()
        if canonical == "openrouter" and not (auth.api_key or auth.account):
            remote = await cls._fetch_remote_models(canonical, auth)
            if remote:
                warnings.append("Using OpenRouter public catalog without credentials.")
                return remote, warnings
            warnings.append("OpenRouter public catalog unavailable. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        if not (auth.api_key or auth.account):
            warnings.append("Authentication is required to fetch remote model catalog.")
            return _fallback_models_for(canonical), warnings

        remote = await cls._fetch_remote_models(canonical, auth)
        if remote:
            return remote, warnings
        warnings.append("Could not fetch remote models from provider API.")
        return _fallback_models_for(canonical), warnings

    @classmethod
    def _parse_remote_model_item(cls, provider_type: str, item: Dict[str, Any]) -> NormalizedModelInfo | None:
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            return None
        description = str(item.get("description") or "").strip() or None
        context_window = cls._safe_int(item.get("context_length"))
        capabilities = cls._infer_capabilities(model_id=model_id, description=description)
        priors = cls._build_prior_scores(
            model_id=model_id,
            capabilities=capabilities,
            context_window=context_window,
        )
        OpsService.seed_model_priors(
            provider_type=provider_type,
            model_id=model_id,
            prior_scores=priors,
            metadata={
                "description": description or "",
                "context_window": context_window,
                "capabilities": capabilities,
            },
        )
        return cls._normalize_model(
            model_id=model_id,
            label=str(item.get("name") or item.get("id") or model_id),
            downloadable=False,
            context_window=context_window,
            description=description,
            capabilities=capabilities,
            weakness=cls._infer_weakness(model_id),
        )

    @classmethod
    async def _fetch_remote_models(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> List[NormalizedModelInfo]:
        base_url = (payload.base_url or "").strip()
        if not base_url:
            base_url = REMOTE_MODELS_BASE_URLS.get(provider_type, "")
        if not base_url:
            return []

        headers = {"Content-Type": "application/json"}
        if payload.api_key:
            headers["Authorization"] = f"Bearer {payload.api_key}"
        elif payload.account:
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
                out = [m for item in items if (m := cls._parse_remote_model_item(provider_type, item)) is not None]
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

    @classmethod
    def list_auth_modes(cls, provider_type: str) -> List[str]:
        canonical = cls._canonical(provider_type)
        return list(ProviderService.capabilities_for(canonical).get("auth_modes_supported") or [])

    @classmethod
    async def _validate_ollama_local(cls, canonical: str) -> ProviderValidateResponse:
        installed = shutil.which("ollama") is not None
        if not installed:
            return ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=["Ollama command not found."],
                error_actionable="Install Ollama and ensure it is available in PATH.",
            )
        ok = await cls._ollama_health()
        return ProviderValidateResponse(
            valid=ok,
            health="ok" if ok else "degraded",
            warnings=[] if ok else ["Ollama runtime not reachable at local endpoint."],
            error_actionable=None if ok else "Start Ollama daemon and retry validation.",
        )

    @classmethod
    async def _validate_cli_account_provider(cls, canonical: str) -> ProviderValidateResponse:
        """Validate CLI-native account mode providers (Codex/Claude).

        Uses the auth services (run_in_executor + subprocess.Popen) to avoid
        asyncio.create_subprocess_* which is unsupported on Windows SelectorEventLoop.
        """
        install_hint = "npm install -g @openai/codex" if canonical == "codex" else "npm install -g @anthropic-ai/claude-code"
        binary = "codex" if canonical == "codex" else "claude"

        if shutil.which(binary) is None:
            return ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=[f"{binary} CLI not found in PATH."],
                error_actionable=f"Install {binary} CLI and retry: {install_hint}",
            )

        # Use auth services — they use run_in_executor + Popen which works on Windows.
        try:
            if canonical == "codex":
                from .codex_auth_service import CodexAuthService
                status = await CodexAuthService.get_auth_status()
            else:
                from .claude_auth_service import ClaudeAuthService
                status = await ClaudeAuthService.get_auth_status()
        except Exception as exc:
            logger.warning("_validate_cli_account_provider auth status error: %s", exc)
            status = {"authenticated": False, "detail": str(exc)}

        recommended = _fallback_models_for(canonical)
        effective_model = recommended[0].id if recommended else None

        if status.get("authenticated"):
            method = status.get("method") or "account"
            return ProviderValidateResponse(
                valid=True,
                health="ok",
                effective_model=effective_model,
                warnings=[f"Validated via local {binary} CLI session ({method})."],
            )

        # CLI is installed but auth status unknown/false — still mark as degraded not down
        detail = status.get("detail") or ""
        return ProviderValidateResponse(
            valid=False,
            health="degraded",
            effective_model=None,
            warnings=[f"{binary} CLI found but session not authenticated. {detail}".strip()],
            error_actionable=f"Run '{binary} login' to authenticate.",
        )

    @classmethod
    def _record_and_return_validation(cls, canonical: str, response: ProviderValidateResponse) -> ProviderValidateResponse:
        ProviderService.record_validation_result(
            provider_type=canonical,
            valid=response.valid,
            health=response.health,
            effective_model=response.effective_model,
            error_actionable=response.error_actionable,
            warnings=response.warnings,
        )
        return response

    @classmethod
    async def validate_credentials(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> ProviderValidateResponse:
        canonical = cls._canonical(provider_type)
        cls.invalidate_cache(provider_type=canonical, reason="manual_test_connection")

        if _mock_mode_enabled(payload):
            mock_models, mock_warnings = await cls.list_available_models(canonical, payload=payload)
            response = ProviderValidateResponse(
                valid=True,
                health="ok",
                effective_model=(mock_models[0].id if mock_models else None),
                warnings=list(mock_warnings),
            )
            return cls._record_and_return_validation(canonical, response)

        if payload.account and str(payload.account).strip().lower().startswith("env:"):
            env_name = ProviderAuthService.parse_env_ref(payload.account)
            if env_name:
                payload = payload.model_copy(update={"account": (ProviderAuthService.resolve_env_expression(f"${{{env_name}}}") or "")})

        if canonical == "ollama_local":
            response = await cls._validate_ollama_local(canonical)
            return cls._record_and_return_validation(canonical, response)

        # Codex/Claude account mode is CLI-native. Do not rely on remote /models.
        if canonical in {"codex", "claude"} and (payload.account is not None or payload.api_key is None):
            response = await cls._validate_cli_account_provider(canonical)
            return cls._record_and_return_validation(canonical, response)

        supports_account = bool(ProviderService.capabilities_for(canonical).get("supports_account_mode", False))
        if payload.account and not supports_account:
            response = ProviderValidateResponse(
                valid=False, health="down",
                warnings=["Account mode is not officially supported for this provider in current environment."],
                error_actionable="Use api_key mode for this provider.",
            )
            return cls._record_and_return_validation(canonical, response)

        if not payload.api_key and not payload.account:
            response = ProviderValidateResponse(
                valid=False, health="down", warnings=["Missing credentials payload."],
                error_actionable="Provide api_key or account according to selected auth mode.",
            )
            return cls._record_and_return_validation(canonical, response)

        remote = await cls._fetch_remote_models(canonical, payload)
        if remote:
            response = ProviderValidateResponse(valid=True, health="ok", effective_model=remote[0].id, warnings=[])
        else:
            response = ProviderValidateResponse(
                valid=False, health="degraded",
                warnings=["Remote API reachable check failed or returned empty catalog."],
                error_actionable="Verify base_url, api_key/org and provider account permissions.",
            )

        return cls._record_and_return_validation(canonical, response)

    @classmethod
    async def _ollama_health(cls) -> bool:
        return await _ollama_health_helper()

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
