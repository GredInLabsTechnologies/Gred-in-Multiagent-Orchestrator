"""Dynamic model discovery via OpenRouter's free /api/v1/models endpoint.

Replaces the hardcoded _OLLAMA_RECOMMENDED list with a live catalog of
open-weight models that support tool calling and can be pulled via Ollama.

OpenRouter's endpoint requires NO API key for read-only model listing.
Results are cached with a configurable TTL to avoid hammering the API.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("orchestrator.openrouter_discovery")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL_SECONDS = 600      # 10 minutes for successful fetches
_CACHE_TTL_FAIL_SECONDS = 60  # 1 minute for failed fetches (faster recovery)
_REQUEST_TIMEOUT = 20.0       # OpenRouter can be slow on cold TCP

# ── Quality tier inference ─────────────────────────────────────────────────
# Based on parameter count extracted from model ID/name patterns.
_TIER_THRESHOLDS = [
    (70, "premium"),
    (14, "balanced"),
    (7, "balanced"),
    (4, "fast"),
    (0, "fast"),
]


def _infer_param_count(model_id: str, name: str) -> Optional[float]:
    """Extract approximate parameter count (in billions) from model ID or name."""
    combined = f"{model_id} {name}".lower()
    # Match patterns like "70b", "7b", "1.5b", "480b", "26b-a4b"
    match = re.search(r"(\d+(?:\.\d+)?)\s*b(?:\b|[-_])", combined)
    if match:
        return float(match.group(1))
    return None


def _infer_quality_tier(params_b: Optional[float]) -> str:
    if params_b is None:
        return "balanced"
    for threshold, tier in _TIER_THRESHOLDS:
        if params_b >= threshold:
            return tier
    return "fast"


# ── Ollama tag inference ───────────────────────────────────────────────────
# Maps OpenRouter model IDs to plausible Ollama pull tags.
# Convention: openrouter "vendor/model-name" → ollama "model-name"

# Known vendor prefix mappings (openrouter vendor → ollama namespace)
_VENDOR_MAP = {
    "qwen": "qwen",
    "meta-llama": "llama",
    "google": "gemma",
    "deepseek": "deepseek",
    "microsoft": "phi",
    "mistralai": "mistral",
    "nvidia": "nemotron",
}

# Known exact mappings for models whose Ollama name doesn't follow conventions
_EXACT_OLLAMA_MAP: Dict[str, str] = {
    "qwen/qwen2.5-coder-32b-instruct": "qwen2.5-coder:32b",
    "qwen/qwen2.5-coder-14b-instruct": "qwen2.5-coder:14b",
    "qwen/qwen2.5-coder-7b-instruct": "qwen2.5-coder:7b",
    "qwen/qwen2.5-coder-1.5b-instruct": "qwen2.5-coder:1.5b",
    "qwen/qwen3-32b": "qwen3:32b",
    "qwen/qwen3-14b": "qwen3:14b",
    "qwen/qwen3-8b": "qwen3:8b",
    "qwen/qwen3-4b": "qwen3:4b",
    "qwen/qwen3-1.7b": "qwen3:1.7b",
    "qwen/qwen3-0.6b": "qwen3:0.6b",
    "qwen/qwen3.5-9b": "qwen3.5:9b",
    "qwen/qwen3.5-4b": "qwen3.5:4b",
    "meta-llama/llama-3.3-70b-instruct": "llama3.3:70b",
    "meta-llama/llama-3.1-8b-instruct": "llama3.1:8b",
    "meta-llama/llama-3.2-3b-instruct": "llama3.2:3b",
    "meta-llama/llama-3.2-1b-instruct": "llama3.2:1b",
    "google/gemma-4-26b-a4b-it": "gemma4:26b",
    "google/gemma-4-9b-it": "gemma4:9b",
    "google/gemma-4-4b-it": "gemma4:4b",
    "google/gemma-4-2b-it": "gemma4:2b",
    "google/gemma-3-27b-it": "gemma3:27b",
    "google/gemma-3-12b-it": "gemma3:12b",
    "google/gemma-3-4b-it": "gemma3:4b",
    "google/gemma-3-1b-it": "gemma3:1b",
    "deepseek/deepseek-r1": "deepseek-r1",
    "deepseek/deepseek-chat-v3.1": "deepseek-v3.1",
    "microsoft/phi-4": "phi4:14b",
    "microsoft/phi-4-mini-instruct": "phi4-mini",
    "mistralai/devstral-small-2505": "devstral",
    "nvidia/llama-3.1-nemotron-nano-8b-v1": "nemotron-nano",
}


def _infer_ollama_tag(openrouter_id: str, hf_id: str | None) -> Optional[str]:
    """Best-effort inference of the Ollama pull tag from OpenRouter model ID."""
    lower = openrouter_id.lower()

    # Exact match first
    if lower in _EXACT_OLLAMA_MAP:
        return _EXACT_OLLAMA_MAP[lower]
    # Strip :free suffix
    base = re.sub(r":free$", "", lower)
    if base in _EXACT_OLLAMA_MAP:
        return _EXACT_OLLAMA_MAP[base]

    # Heuristic: vendor/model-name-XBb → model-name:Xb
    parts = base.split("/", 1)
    if len(parts) != 2:
        return None
    _vendor, model_part = parts

    # Remove common suffixes
    model_part = re.sub(r"-instruct$|-it$|-chat$", "", model_part)

    # Extract size
    size_match = re.search(r"-(\d+(?:\.\d+)?b)(?:-|$)", model_part)
    if size_match:
        size = size_match.group(1)
        name = model_part[:size_match.start()]
        return f"{name}:{size}"

    return None


# ── Cache ──────────────────────────────────────────────────────────────────

@dataclass
class _CachedDiscovery:
    models: List[Dict[str, Any]] = field(default_factory=list)
    fetched_at: float = 0.0


_cache = _CachedDiscovery()
_fetch_lock = asyncio.Lock()


# ── Public API ─────────────────────────────────────────────────────────────

@dataclass
class DiscoveredModel:
    """A model discovered via OpenRouter that is likely pullable in Ollama."""
    id: str                     # OpenRouter ID (e.g. "qwen/qwen3.5-4b")
    ollama_tag: str             # Inferred Ollama tag (e.g. "qwen3.5:4b")
    label: str                  # Human-readable name
    quality_tier: str           # "premium", "balanced", "fast"
    context_length: int
    supports_tools: bool
    supports_vision: bool
    params_b: Optional[float]   # Estimated parameter count in billions
    pricing_prompt_per_m: float # USD per million tokens (on OpenRouter)
    hugging_face_id: str        # HuggingFace repo ID


async def fetch_open_weight_models(
    *,
    require_tools: bool = True,
    max_params_b: Optional[float] = None,
) -> List[DiscoveredModel]:
    """Fetch open-weight models from OpenRouter, filtered and ranked.

    Args:
        require_tools: Only include models that support tool calling.
        max_params_b: Exclude models above this parameter count (VRAM filter).

    Returns:
        List of DiscoveredModel sorted by quality_tier desc, params desc.
    """
    global _cache

    now = time.monotonic()
    ttl = _CACHE_TTL_SECONDS if _cache.models else _CACHE_TTL_FAIL_SECONDS
    if _cache.fetched_at and (now - _cache.fetched_at) < ttl:
        raw = _cache.models
    else:
        async with _fetch_lock:
            # Double-check after acquiring lock
            ttl2 = _CACHE_TTL_SECONDS if _cache.models else _CACHE_TTL_FAIL_SECONDS
            if _cache.fetched_at and (time.monotonic() - _cache.fetched_at) < ttl2:
                raw = _cache.models
            else:
                raw = await _fetch_from_openrouter()
                _cache.models = raw
                _cache.fetched_at = time.monotonic()

    results: List[DiscoveredModel] = []
    for m in raw:
        hf_id = m.get("hugging_face_id")
        if not hf_id:
            continue  # Proprietary model

        model_id = m.get("id", "")
        name = m.get("name", "")
        params_b = _infer_param_count(model_id, name)
        supported_params = m.get("supported_parameters") or []
        has_tools = "tools" in supported_params

        if require_tools and not has_tools:
            continue

        if max_params_b is not None and params_b is not None and params_b > max_params_b:
            logger.debug("Filtering %s (params_b=%s > max=%s)", model_id, params_b, max_params_b)
            continue

        ollama_tag = _infer_ollama_tag(model_id, hf_id)
        if not ollama_tag:
            continue  # Can't infer Ollama tag — skip

        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", 0))
        arch = m.get("architecture", {})
        input_mods = arch.get("input_modalities") or []

        results.append(DiscoveredModel(
            id=model_id,
            ollama_tag=ollama_tag,
            label=name,
            quality_tier=_infer_quality_tier(params_b),
            context_length=int(m.get("context_length") or 0),
            supports_tools=has_tools,
            supports_vision="image" in input_mods,
            params_b=params_b,
            pricing_prompt_per_m=prompt_price * 1_000_000,
            hugging_face_id=hf_id,
        ))

    # Sort: premium first, then by param count descending
    tier_order = {"premium": 0, "balanced": 1, "fast": 2}
    results.sort(key=lambda x: (tier_order.get(x.quality_tier, 9), -(x.params_b or 0)))

    # Deduplicate by ollama_tag — keep the first (highest-ranked) entry per tag.
    # Multiple OpenRouter entries can resolve to the same Ollama tag
    # (e.g. "vendor/model" and "vendor/model:free").
    seen_tags: set[str] = set()
    deduped: List[DiscoveredModel] = []
    for m in results:
        if m.ollama_tag not in seen_tags:
            seen_tags.add(m.ollama_tag)
            deduped.append(m)
    return deduped


_MAX_RECOMMENDED = 30  # Keep the catalog manageable for UI/MCP consumers


def to_recommended_dicts(
    models: List[DiscoveredModel], *, max_results: int = _MAX_RECOMMENDED
) -> List[Dict[str, Any]]:
    """Convert to the format expected by _OLLAMA_RECOMMENDED consumers.

    Returns at most *max_results* entries, already sorted by tier/params.
    Includes context_window when available.
    """
    return [
        {
            "id": m.ollama_tag,
            "label": m.label,
            "quality_tier": m.quality_tier,
            "context_window": m.context_length or None,
        }
        for m in models[:max_results]
    ]


# ── Hardcoded fallback ─────────────────────────────────────────────────────
# Used when OpenRouter is unreachable. Kept minimal and current as of 2026-04.
FALLBACK_RECOMMENDED = [
    {"id": "qwen3.5:4b",         "label": "Qwen 3.5 4B",             "quality_tier": "fast"},
    {"id": "qwen3.5:9b",         "label": "Qwen 3.5 9B",             "quality_tier": "balanced"},
    {"id": "qwen2.5-coder:7b",   "label": "Qwen 2.5 Coder 7B",      "quality_tier": "balanced"},
    {"id": "qwen2.5-coder:32b",  "label": "Qwen 2.5 Coder 32B",     "quality_tier": "premium"},
    {"id": "gemma4:4b",           "label": "Gemma 4 4B",              "quality_tier": "fast"},
    {"id": "gemma4:9b",           "label": "Gemma 4 9B",              "quality_tier": "balanced"},
    {"id": "gemma4:26b",          "label": "Gemma 4 26B MoE",         "quality_tier": "premium"},
    {"id": "llama3.2:3b",        "label": "Llama 3.2 3B",            "quality_tier": "fast"},
    {"id": "llama3.1:8b",        "label": "Llama 3.1 8B",            "quality_tier": "balanced"},
    {"id": "devstral",           "label": "Devstral (Mistral)",       "quality_tier": "premium"},
    {"id": "phi4:14b",           "label": "Phi-4 14B",               "quality_tier": "balanced"},
    {"id": "nemotron-nano",      "label": "Nemotron Nano 8B",        "quality_tier": "balanced"},
    {"id": "deepseek-r1",        "label": "DeepSeek R1",             "quality_tier": "premium"},
]


async def get_ollama_recommended(
    *, max_params_b: float = 80.0,
) -> List[Dict[str, Any]]:
    """Get the recommended Ollama models list — dynamic with fallback.

    Tries OpenRouter first; falls back to a hardcoded list if the API
    is unreachable or returns no usable models.

    Args:
        max_params_b: Exclude models above this parameter count.
            Default 80B covers high-end consumer GPUs; anything larger
            is impractical for local Ollama inference.
    """
    try:
        discovered = await fetch_open_weight_models(
            require_tools=True, max_params_b=max_params_b,
        )
        logger.info(
            "get_ollama_recommended: max_params_b=%s, discovered=%d models",
            max_params_b, len(discovered),
        )
        if discovered:
            result = to_recommended_dicts(discovered)
            logger.info("get_ollama_recommended: returning %d recommended", len(result))
            return result
    except Exception:
        logger.warning("OpenRouter discovery failed; using fallback recommended list", exc_info=True)
    return list(FALLBACK_RECOMMENDED)


# ── Internal ───────────────────────────────────────────────────────────────

async def _fetch_from_openrouter() -> List[Dict[str, Any]]:
    """Fetch the raw model list from OpenRouter. No auth required."""
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            logger.info("OpenRouter discovery: %d models fetched", len(models))
            return models
    except Exception:
        logger.warning("Failed to fetch models from OpenRouter", exc_info=True)
        return []
