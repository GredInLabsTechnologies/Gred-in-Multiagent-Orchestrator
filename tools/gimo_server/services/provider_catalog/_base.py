from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

from ...ops_models import (
    NormalizedModelInfo,
    ProviderModelInstallResponse,
    ProviderModelsCatalogResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from ..providers.service import ProviderService
from ..providers.auth_service import ProviderAuthService


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
        # Groq keeps an OpenAI-compatible API and tool-use support; bias toward coding/agentic models.
        {"id": "qwen/qwen3-32b",        "label": "Qwen 3 32B"},
        {"id": "openai/gpt-oss-120b",   "label": "GPT-OSS 120B"},
        {"id": "openai/gpt-oss-20b",    "label": "GPT-OSS 20B"},
        {"id": "moonshotai/kimi-k2-instruct-0905", "label": "Kimi K2 Instruct 0905"},
    ],
    "cloudflare-workers-ai": [
        # Workers AI catalog is account-scoped; these are the highest-signal coding/agentic defaults.
        {"id": "@cf/qwen/qwen3-30b-a3b-fp8",          "label": "Qwen 3 30B A3B FP8"},
        {"id": "@cf/qwen/qwen2.5-coder-32b-instruct", "label": "Qwen 2.5 Coder 32B"},
        {"id": "@cf/openai/gpt-oss-120b",             "label": "GPT-OSS 120B"},
        {"id": "@cf/openai/gpt-oss-20b",              "label": "GPT-OSS 20B"},
        {"id": "@cf/moonshotai/kimi-k2.5",            "label": "Kimi K2.5"},
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
            cmd, shell=(sys.platform == "win32"),  # nosec B602
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=clean_env,  # remove nested-session guard so claude/codex CLIs work
        )
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, (out or b"").decode("utf-8", errors="replace").strip()
    except Exception as exc:
        return -1, str(exc)


def _fallback_models_for(provider_type: str) -> List[NormalizedModelInfo]:
    return [
        ProviderCatalogBase._normalize_model(
            model_id=m["id"],
            label=m.get("label"),
            downloadable=False,
        )
        for m in _DEFAULT_PROVIDER_MODELS.get(provider_type, [])
    ]


class ProviderCatalogBase:
    """Base class with shared constants, cache, static data, and utility methods."""
    _CATALOG_CACHE: Dict[str, Tuple[float, ProviderModelsCatalogResponse]] = {}
    _INSTALL_JOBS: Dict[str, Dict[str, Any]] = {}
    _CATALOG_TTL_SECONDS: Dict[str, int] = {
        "ollama_local": 30,
        "openai": 300,
        "codex": 300,
        "claude": 300,
        "anthropic": 300,
        "groq": 300,
        "cloudflare-workers-ai": 300,
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
    def list_auth_modes(cls, provider_type: str) -> List[str]:
        canonical = cls._canonical(provider_type)
        return list(ProviderService.capabilities_for(canonical).get("auth_modes_supported") or [])

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
