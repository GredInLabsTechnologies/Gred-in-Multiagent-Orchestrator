from __future__ import annotations

import os
from typing import Any, Dict, Optional


class ProviderCapabilityService:
    """Single-responsibility service for provider taxonomy and capability matrix."""

    _PROVIDER_TYPE_ALIASES = {
        "ollama": "ollama_local",
        "local_ollama": "ollama_local",
        "ollama_local": "ollama_local",
        "vllm": "vllm",
        "llama-cpp": "llama-cpp",
        "llamacpp": "llama-cpp",
        "llama_cpp": "llama-cpp",
        "tgi": "tgi",
        "openai_compat": "custom_openai_compatible",
        "custom": "custom_openai_compatible",
        "custom_openai_compatible": "custom_openai_compatible",
        "openai": "openai",
        "anthropic": "anthropic",
        "claude": "claude",
        "google": "google",
        "gemini": "google",
        "mistral": "mistral",
        "cohere": "cohere",
        "deepseek": "deepseek",
        "qwen": "qwen",
        "moonshot": "moonshot",
        "zai": "zai",
        "minimax": "minimax",
        "baidu": "baidu",
        "tencent": "tencent",
        "bytedance": "bytedance",
        "iflytek": "iflytek",
        "01-ai": "01-ai",
        "01ai": "01-ai",
        "codex": "codex",
        "groq": "groq",
        "openrouter": "openrouter",
        "together": "together",
        "fireworks": "fireworks",
        "replicate": "replicate",
        "huggingface": "huggingface",
        "azure-openai": "azure-openai",
        "azure_openai": "azure-openai",
        "aws-bedrock": "aws-bedrock",
        "aws_bedrock": "aws-bedrock",
        "vertex-ai": "vertex-ai",
        "vertex_ai": "vertex-ai",
        "sglang": "sglang",
        "lm_studio": "lm_studio",
        "lmstudio": "lm_studio",
        "lm-studio": "lm_studio",
    }

    _CAPABILITY_MATRIX: Dict[str, Dict[str, Any]] = {
        "ollama_local": {
            "auth_modes_supported": ["none", "api_key_optional"],
            "can_install": True,
            "install_method": "local_runtime",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": False,
        },
        "sglang": {
            "auth_modes_supported": ["none"],
            "can_install": False,
            "install_method": "manual",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": False,
        },
        "lm_studio": {
            "auth_modes_supported": ["none"],
            "can_install": False,
            "install_method": "manual",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": False,
        },
        "vllm": {
            "auth_modes_supported": ["none", "api_key_optional"],
            "can_install": False,
            "install_method": "manual",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": False,
        },
        "llama-cpp": {
            "auth_modes_supported": ["none", "api_key_optional"],
            "can_install": False,
            "install_method": "manual",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": False,
        },
        "tgi": {
            "auth_modes_supported": ["none", "api_key_optional"],
            "can_install": False,
            "install_method": "manual",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": False,
        },
        "openai": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "anthropic": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "codex": {
            "auth_modes_supported": ["api_key", "account"],
            "can_install": False,
            "install_method": "cli",
            "supports_account_mode": True,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "claude": {
            "auth_modes_supported": ["api_key", "account"],
            "can_install": False,
            "install_method": "cli",
            "supports_account_mode": True,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "google": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "mistral": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "cohere": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "deepseek": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "qwen": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "moonshot": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "zai": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "minimax": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "baidu": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "tencent": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "bytedance": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "iflytek": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "01-ai": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "groq": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "openrouter": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "together": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "fireworks": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "replicate": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "huggingface": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "azure-openai": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "aws-bedrock": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "vertex-ai": {
            "auth_modes_supported": ["api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": True,
            "requires_remote_api": True,
        },
        "custom_openai_compatible": {
            "auth_modes_supported": ["none", "api_key"],
            "can_install": False,
            "install_method": "none",
            "supports_account_mode": False,
            "supports_recommended_models": False,
            "requires_remote_api": True,
        },
    }

    @classmethod
    def normalize_provider_type(cls, raw_type: Optional[str]) -> str:
        key = (raw_type or "custom_openai_compatible").strip().lower()
        return cls._PROVIDER_TYPE_ALIASES.get(key, "custom_openai_compatible")

    @classmethod
    def _is_account_mode_enabled(cls, provider_type: str) -> bool:
        canonical = cls.normalize_provider_type(provider_type)
        if canonical == "openai":
            return str(os.environ.get("ORCH_OPENAI_ACCOUNT_MODE_ENABLED", "")).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        if canonical in {"codex", "claude"}:
            return True
        return False

    @classmethod
    def capabilities_for(cls, provider_type: Optional[str]) -> Dict[str, Any]:
        canonical = cls.normalize_provider_type(provider_type)
        caps = dict(cls._CAPABILITY_MATRIX.get(canonical, cls._CAPABILITY_MATRIX["custom_openai_compatible"]))
        if canonical == "openai":
            supports_account = cls._is_account_mode_enabled(canonical)
            caps["supports_account_mode"] = supports_account
            auth_modes = list(caps.get("auth_modes_supported") or [])
            if supports_account and "account" not in auth_modes:
                auth_modes.append("account")
            if not supports_account:
                auth_modes = [m for m in auth_modes if m != "account"]
            caps["auth_modes_supported"] = auth_modes
        return caps

    @classmethod
    def get_capability_matrix(cls) -> Dict[str, Dict[str, Any]]:
        return {k: cls.capabilities_for(k) for k in cls._CAPABILITY_MATRIX.keys()}
