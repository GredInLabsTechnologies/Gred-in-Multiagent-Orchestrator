"""Dynamic model inventory built from user's configured providers."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("orchestrator.model_inventory")

CACHE_TTL = 300  # 5 minutes

# Heuristic patterns to infer quality tier (1-5) from model ID
_TIER_PATTERNS: list[tuple[int, re.Pattern]] = [
    (5, re.compile(r"opus|ultra|max|o1-pro|gpt-4-?o(?!-mini)", re.I)),
    (4, re.compile(r"sonnet|pro|70b|72b|65b|claude-3|gpt-4(?!o)", re.I)),
    (3, re.compile(r"haiku|13b|14b|8b|7b|medium|gpt-3\.5|gpt-4o-mini|mistral-large", re.I)),
    (2, re.compile(r"3b|4b|small|mini|phi-?[23]|gemma.*2b", re.I)),
    (1, re.compile(r"1b|0\.5b|tiny|nano|qwen.*0\.5", re.I)),
]

# Infer capabilities from model name
_CAP_PATTERNS: dict[str, re.Pattern] = {
    "code": re.compile(r"code|coder|starcoder|codellama|deepseek-coder", re.I),
    "reasoning": re.compile(r"opus|o1|o3|deepseek-r1|qwq", re.I),
    "vision": re.compile(r"vision|llava|bakllava|moondream", re.I),
}


def _parse_size_gb(size_str: Optional[str]) -> Optional[float]:
    if not size_str:
        return None
    s = str(size_str).strip().lower()
    # "4.7 GB" or "4700000000" (bytes)
    m = re.match(r"([\d.]+)\s*(gb|mb|tb)?", s)
    if not m:
        try:
            val = float(s)
            if val > 1_000_000:
                return round(val / (1024 ** 3), 2)
            return val
        except ValueError:
            return None
    val = float(m.group(1))
    unit = m.group(2) or "gb"
    if unit == "mb":
        return round(val / 1024, 2)
    if unit == "tb":
        return round(val * 1024, 2)
    return round(val, 2)


def _infer_tier(model_id: str, size_gb: Optional[float] = None) -> int:
    for tier, pattern in _TIER_PATTERNS:
        if pattern.search(model_id):
            return tier
    if size_gb:
        if size_gb < 2:
            return 1
        if size_gb < 5:
            return 2
        if size_gb < 10:
            return 3
        if size_gb < 50:
            return 4
        return 5
    return 3  # default: mid-tier


def _infer_capabilities(model_id: str) -> set[str]:
    caps = {"chat"}  # All models can chat
    for cap, pattern in _CAP_PATTERNS.items():
        if pattern.search(model_id):
            caps.add(cap)
    return caps


@dataclass
class ModelEntry:
    model_id: str
    provider_id: str
    provider_type: str
    is_local: bool
    quality_tier: int
    size_gb: Optional[float] = None
    context_window: Optional[int] = None
    capabilities: set[str] = field(default_factory=lambda: {"chat"})
    cost_input: float = 0.0   # per 1M tokens
    cost_output: float = 0.0  # per 1M tokens


class ModelInventoryService:
    """Builds and caches a unified view of all available models across providers."""

    _cache: list[ModelEntry] = []
    _cache_ts: float = 0.0

    @classmethod
    def invalidate(cls) -> None:
        cls._cache = []
        cls._cache_ts = 0.0

    @classmethod
    async def refresh_inventory(cls) -> list[ModelEntry]:
        from .providers.service import ProviderService
        from .providers.catalog_service import ProviderCatalogService
        from .economy.cost_service import CostService

        cfg = ProviderService.get_config()
        if not cfg:
            cls._cache = []
            cls._cache_ts = time.time()
            return []

        entries: list[ModelEntry] = []
        seen: set[tuple[str, str]] = set()  # (model_id, provider_id)

        for pid, pentry in cfg.providers.items():
            ptype = ProviderService.normalize_provider_type(pentry.provider_type or pentry.type)
            is_local = not bool((pentry.capabilities or {}).get("requires_remote_api", True))

            # Get installed models from catalog (async)
            try:
                catalog_models = await ProviderCatalogService.list_installed_models(ptype)
            except Exception:
                catalog_models = []

            for m in catalog_models:
                key = (m.id, pid)
                if key in seen:
                    continue
                seen.add(key)
                size = _parse_size_gb(m.size)
                tier = _infer_tier(m.id, size)
                # Override tier if catalog has quality_tier string
                if m.quality_tier:
                    qt = str(m.quality_tier).lower()
                    tier_map = {"low": 1, "economy": 2, "balanced": 3, "premium": 4, "flagship": 5}
                    tier = tier_map.get(qt, tier)

                pricing = CostService.get_pricing(m.id)
                entries.append(ModelEntry(
                    model_id=m.id,
                    provider_id=pid,
                    provider_type=ptype,
                    is_local=is_local,
                    quality_tier=pricing.get("quality_tier") or tier,
                    size_gb=size,
                    context_window=m.context_window or pricing.get("context_window"),
                    capabilities=_infer_capabilities(m.id),
                    cost_input=pricing.get("input", 0.0),
                    cost_output=pricing.get("output", 0.0),
                ))

            # Always include the provider's configured model even if not in catalog
            active_model = pentry.model or pentry.model_id
            if active_model:
                key = (active_model, pid)
                if key not in seen:
                    seen.add(key)
                    pricing = CostService.get_pricing(active_model)
                    entries.append(ModelEntry(
                        model_id=active_model,
                        provider_id=pid,
                        provider_type=ptype,
                        is_local=is_local,
                        quality_tier=pricing.get("quality_tier") or _infer_tier(active_model),
                        context_window=pricing.get("context_window"),
                        capabilities=_infer_capabilities(active_model),
                        cost_input=pricing.get("input", 0.0),
                        cost_output=pricing.get("output", 0.0),
                    ))

        cls._cache = entries
        cls._cache_ts = time.time()
        logger.info("Model inventory refreshed: %d models across %d providers",
                     len(entries), len(cfg.providers))

        # Enrich capabilities from external benchmarks and seed GICS priors.
        # Runs in background to avoid blocking inventory refresh.
        try:
            from . import benchmark_enrichment_service as bes
            profiles = await bes.refresh_benchmarks()
            if profiles:
                for entry in entries:
                    profile = bes.lookup_model(entry.model_id, profiles)
                    if profile:
                        # Enrich capabilities from benchmark dimensions
                        if profile.dimensions.get("coding", 0) > 0.6:
                            entry.capabilities.add("code")
                        if profile.dimensions.get("reasoning", 0) > 0.6:
                            entry.capabilities.add("reasoning")
                        if profile.dimensions.get("math", 0) > 0.6:
                            entry.capabilities.add("math")

                # Seed GICS priors per provider group
                try:
                    from .gics_service import GicsService
                    gics = GicsService()
                    by_provider: dict[str, list[str]] = {}
                    for e in entries:
                        by_provider.setdefault(e.provider_type, []).append(e.model_id)
                    for ptype, model_ids in by_provider.items():
                        await bes.seed_gics_priors(gics, ptype, model_ids, profiles)
                except Exception:
                    logger.debug("GICS prior seeding skipped (daemon may be unavailable)")
        except Exception:
            logger.debug("Benchmark enrichment skipped", exc_info=True)

        return entries

    @classmethod
    def get_available_models(cls) -> list[ModelEntry]:
        """Returns cached inventory (sync). Call refresh_inventory() to update."""
        if cls._cache:
            return cls._cache
        # Build a minimal inventory from provider config (sync, no catalog)
        return cls._build_minimal_inventory()

    @classmethod
    def _build_minimal_inventory(cls) -> list[ModelEntry]:
        """Sync fallback: build inventory from provider config only (no async catalog)."""
        from .providers.service import ProviderService
        from .economy.cost_service import CostService

        cfg = ProviderService.get_config()
        if not cfg:
            return []

        entries: list[ModelEntry] = []
        for pid, pentry in cfg.providers.items():
            ptype = ProviderService.normalize_provider_type(pentry.provider_type or pentry.type)
            is_local = not bool((pentry.capabilities or {}).get("requires_remote_api", True))
            model = pentry.model or pentry.model_id
            if model:
                pricing = CostService.get_pricing(model)
                entries.append(ModelEntry(
                    model_id=model, provider_id=pid, provider_type=ptype,
                    is_local=is_local, quality_tier=_infer_tier(model),
                    capabilities=_infer_capabilities(model),
                    cost_input=pricing.get("input", 0.0),
                    cost_output=pricing.get("output", 0.0),
                ))
        cls._cache = entries
        cls._cache_ts = time.time()
        return entries

    @classmethod
    def get_models_for_tier(cls, min_tier: int, max_tier: int = 5) -> list[ModelEntry]:
        return [m for m in cls.get_available_models() if min_tier <= m.quality_tier <= max_tier]

    @classmethod
    def get_cheapest_for_capability(cls, capability: str, min_tier: int = 1) -> Optional[ModelEntry]:
        candidates = [m for m in cls.get_available_models()
                      if capability in m.capabilities and m.quality_tier >= min_tier]
        if not candidates:
            return None
        return min(candidates, key=lambda m: m.cost_input + m.cost_output)

    @classmethod
    def get_best_for_capability(cls, capability: str) -> Optional[ModelEntry]:
        candidates = [m for m in cls.get_available_models() if capability in m.capabilities]
        if not candidates:
            return None
        return max(candidates, key=lambda m: m.quality_tier)

    @classmethod
    def find_model(cls, model_id: str) -> Optional[ModelEntry]:
        for m in cls.get_available_models():
            if m.model_id == model_id:
                return m
        return None
