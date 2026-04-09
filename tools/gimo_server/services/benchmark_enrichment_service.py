"""Benchmark enrichment — fetch external capability scores and seed GICS priors.

Data sources (all free, no API key required):
  1. LMArena (lmarena-ai/leaderboard-dataset) — Bradley-Terry ratings across
     17 categories: overall, coding, math, creative_writing, etc.
     Covers both proprietary and open-weight models.
  2. Open LLM Leaderboard (open-llm-leaderboard/contents) — Numeric benchmark
     scores: IFEval, BBH, MATH, GPQA, MUSR, MMLU-PRO.
     Open-weight models only.

Architecture:
  External benchmarks are fetched periodically and stored as a local cache JSON.
  On model inventory refresh, scores are normalized and seeded into GICS as
  priors via GicsService.seed_model_prior(). The trust engine's blending formula
  (20% prior + 80% observed) ensures GIMO's own operational evidence takes
  precedence as it accumulates experience.

  GICS is the authority. External data is the starting point.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("orchestrator.benchmark_enrichment")

# ── HuggingFace datasets-server endpoints (free, no auth) ────────────────
_HF_DS_BASE = "https://datasets-server.huggingface.co/rows"
_LMARENA_DATASET = "lmarena-ai/leaderboard-dataset"
_LMARENA_CONFIG = "text_style_control"
_LMARENA_SPLIT = "latest"
_OPENLLM_DATASET = "open-llm-leaderboard/contents"
_OPENLLM_CONFIG = "default"
_OPENLLM_SPLIT = "train"

_REQUEST_TIMEOUT = 25.0
_PAGE_SIZE = 100
_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds, multiplied by attempt number

# ── Local cache paths ─────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LMARENA_CACHE = _DATA_DIR / "lmarena_benchmarks.json"
_OPENLLM_CACHE = _DATA_DIR / "openllm_benchmarks.json"
_ENRICHED_CACHE = _DATA_DIR / "model_capabilities.json"
_CACHE_MAX_AGE_SECONDS = 86400 * 7  # 7 days

# ── GIMO capability dimensions (normalized names) ─────────────────────────
# Maps external benchmark/category names → GIMO dimension names.
# Scores are normalized to 0.0–1.0 before seeding into GICS.

# LMArena categories → GIMO dimensions
_LMARENA_DIM_MAP: Dict[str, str] = {
    "overall": "overall",
    "hard_prompts": "hard_tasks",
    "creative_writing": "creative",
    "multi_turn": "multi_turn",
    "longer_query": "long_context",
    "expert": "expert_knowledge",
    "industry_software_and_it_services": "coding",
    "industry_mathematical": "math",
    "industry_life_and_physical_and_social_science": "science",
    "industry_writing_and_literature_and_language": "writing",
    "industry_entertainment_and_sports_and_media": "general_knowledge",
    "industry_business_and_management_and_financial_operations": "business",
}

# Open LLM Leaderboard benchmarks → GIMO dimensions
_OPENLLM_DIM_MAP: Dict[str, str] = {
    "IFEval": "instruction_following",
    "BBH": "reasoning",
    "MATH Lvl 5": "math",
    "GPQA": "expert_knowledge",
    "MUSR": "multi_step_reasoning",
    "MMLU-PRO": "general_knowledge",
    "Average ⬆️": "overall",
}


# ── Model name normalization ─────────────────────────────────────────────
# External sources use different naming conventions. These helpers normalize
# to a canonical form for matching against GIMO's model inventory.

def _normalize_model_name(name: str) -> str:
    """Produce a canonical lowercase key for fuzzy matching."""
    s = name.lower().strip()
    # Remove common suffixes/prefixes
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)  # remove parenthetical
    s = re.sub(r"-?(instruct|chat|it|hf|gguf|gptq|awq|fp16|bf16)$", "", s)
    s = re.sub(r"[^a-z0-9.]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _build_alias_map(name: str) -> List[str]:
    """Generate multiple alias keys from a model name for fuzzy matching."""
    base = _normalize_model_name(name)
    aliases = [base]
    # "org/model" → also try just "model"
    if "/" in base:
        aliases.append(base.split("/", 1)[1])
    # "qwen2.5-coder-7b" → also try "qwen2.5-coder:7b" (Ollama convention)
    size_match = re.search(r"-(\d+(?:\.\d+)?b)$", base)
    if size_match:
        aliases.append(base[:size_match.start()] + ":" + size_match.group(1))
    return aliases


# ── Data types ────────────────────────────────────────────────────────────

class ModelBenchmarks:
    """Aggregated benchmark profile for one model."""

    __slots__ = ("model_id", "aliases", "dimensions", "sources", "params_b", "updated_at")

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.aliases: List[str] = _build_alias_map(model_id)
        self.dimensions: Dict[str, float] = {}  # dim_name → 0.0-1.0
        self.sources: Dict[str, str] = {}       # dim_name → source tag
        self.params_b: Optional[float] = None
        self.updated_at: float = time.time()

    def set_dim(self, dim: str, score: float, source: str) -> None:
        """Set a dimension score (0.0-1.0). Higher source priority wins."""
        # If we already have this dim from a higher-priority source, skip
        existing_source = self.sources.get(dim)
        if existing_source and _source_priority(existing_source) > _source_priority(source):
            return
        self.dimensions[dim] = max(0.0, min(1.0, score))
        self.sources[dim] = source

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "aliases": self.aliases,
            "dimensions": self.dimensions,
            "sources": self.sources,
            "params_b": self.params_b,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelBenchmarks":
        obj = cls(d["model_id"])
        obj.aliases = d.get("aliases", obj.aliases)
        obj.dimensions = d.get("dimensions", {})
        obj.sources = d.get("sources", {})
        obj.params_b = d.get("params_b")
        obj.updated_at = d.get("updated_at", time.time())
        return obj


def _source_priority(source: str) -> int:
    """Higher = higher priority. GICS > LMArena > OpenLLM > inferred."""
    return {"gics": 100, "lmarena": 50, "openllm": 40, "inferred": 10}.get(source, 0)


# ── Fetchers ──────────────────────────────────────────────────────────────

async def _fetch_hf_dataset_rows(
    dataset: str, config: str, split: str, *, max_rows: int = 10000,
) -> List[Dict[str, Any]]:
    """Fetch rows from HuggingFace datasets-server, paginating as needed.

    Includes retry with exponential backoff for 429 rate-limit responses,
    and a polite delay between pages to stay under rate limits.
    """
    import asyncio as _asyncio

    all_rows: List[Dict[str, Any]] = []
    offset = 0
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        while offset < max_rows:
            url = (
                f"{_HF_DS_BASE}?dataset={dataset}&config={config}"
                f"&split={split}&offset={offset}&length={_PAGE_SIZE}"
            )
            data = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 429:
                        wait = _RETRY_BACKOFF * (2 ** attempt)  # exponential: 4, 8, 16s
                        logger.info("HF rate-limited (429), retrying in %.1fs (attempt %d/%d)", wait, attempt, _MAX_RETRIES)
                        await _asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < _MAX_RETRIES:
                        wait = _RETRY_BACKOFF * (2 ** attempt)
                        logger.info("HF rate-limited (429), retrying in %.1fs (attempt %d/%d)", wait, attempt, _MAX_RETRIES)
                        await _asyncio.sleep(wait)
                        continue
                    logger.warning("HF dataset fetch failed at offset %d: %s", offset, e)
                    break
                except Exception as e:
                    logger.warning("HF dataset fetch failed at offset %d: %s", offset, e)
                    break

            if data is None:
                break

            rows = data.get("rows", [])
            if not rows:
                break
            for r in rows:
                all_rows.append(r.get("row", r))
            total = data.get("num_rows_total", 0)
            offset += len(rows)
            if offset >= total:
                break

            # Polite delay between pages to respect rate limits
            await _asyncio.sleep(0.3)

    logger.info("Fetched %d rows from %s/%s", len(all_rows), dataset, config)
    return all_rows


async def fetch_lmarena_scores() -> Dict[str, ModelBenchmarks]:
    """Fetch LMArena leaderboard and organize by model."""
    rows = await _fetch_hf_dataset_rows(
        _LMARENA_DATASET, _LMARENA_CONFIG, _LMARENA_SPLIT,
        max_rows=5000,  # ~300 models × 17 categories
    )

    # LMArena ratings are typically 800-1600. Normalize to 0-1 range.
    # We use percentile ranking within each category for fairness.
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        cat = row.get("category", "overall")
        by_category.setdefault(cat, []).append(row)

    models: Dict[str, ModelBenchmarks] = {}
    for cat, cat_rows in by_category.items():
        dim = _LMARENA_DIM_MAP.get(cat)
        if not dim:
            continue

        # Sort by rating descending → percentile rank
        cat_rows.sort(key=lambda r: float(r.get("rating") or 0), reverse=True)
        n = len(cat_rows)
        for rank, row in enumerate(cat_rows):
            name = row.get("model_name", "")
            if not name:
                continue
            key = _normalize_model_name(name)
            if key not in models:
                models[key] = ModelBenchmarks(name)
            # Percentile score: top model = 1.0, bottom = 0.0
            percentile = 1.0 - (rank / max(1, n - 1)) if n > 1 else 0.5
            models[key].set_dim(dim, percentile, "lmarena")

    logger.info("LMArena: %d models with capability profiles", len(models))
    return models


async def fetch_openllm_scores() -> Dict[str, ModelBenchmarks]:
    """Fetch Open LLM Leaderboard scores."""
    rows = await _fetch_hf_dataset_rows(
        _OPENLLM_DATASET, _OPENLLM_CONFIG, _OPENLLM_SPLIT,
        max_rows=2000,  # Top 2000 models (sorted by score)
    )

    models: Dict[str, ModelBenchmarks] = {}
    for row in rows:
        fullname = row.get("fullname", "")
        if not fullname:
            continue
        key = _normalize_model_name(fullname)
        if key in models:
            continue  # Deduplicate: keep first (newer)

        mb = ModelBenchmarks(fullname)
        # Extract parameter count
        params = row.get("#Params (B)")
        if params is not None:
            try:
                mb.params_b = float(params)
            except (ValueError, TypeError):
                pass

        # Extract benchmark scores (already 0-100 scale → normalize to 0-1)
        for bench_name, dim in _OPENLLM_DIM_MAP.items():
            score = row.get(bench_name)
            if score is not None:
                try:
                    mb.set_dim(dim, float(score) / 100.0, "openllm")
                except (ValueError, TypeError):
                    pass

        if mb.dimensions:
            models[key] = mb

    logger.info("OpenLLM: %d models with benchmark scores", len(models))
    return models


# ── Merge & persistence ───────────────────────────────────────────────────

def _merge_profiles(
    lmarena: Dict[str, ModelBenchmarks],
    openllm: Dict[str, ModelBenchmarks],
) -> Dict[str, ModelBenchmarks]:
    """Merge LMArena and OpenLLM profiles. LMArena takes priority on conflicts."""
    merged: Dict[str, ModelBenchmarks] = {}

    # Start with OpenLLM (lower priority)
    for key, mb in openllm.items():
        merged[key] = mb

    # Overlay LMArena (higher priority)
    for key, mb in lmarena.items():
        if key in merged:
            # Merge dimensions: LMArena wins on conflicts (via _source_priority)
            for dim, score in mb.dimensions.items():
                merged[key].set_dim(dim, score, mb.sources[dim])
        else:
            merged[key] = mb

    return merged


def _save_cache(profiles: Dict[str, ModelBenchmarks]) -> None:
    """Persist enriched profiles to disk."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": time.time(),
        "models": {k: v.to_dict() for k, v in profiles.items()},
    }
    _ENRICHED_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved %d enriched model profiles to %s", len(profiles), _ENRICHED_CACHE.name)


def _load_cache() -> Optional[Dict[str, ModelBenchmarks]]:
    """Load cached profiles if fresh enough."""
    if not _ENRICHED_CACHE.exists():
        return None
    try:
        raw = json.loads(_ENRICHED_CACHE.read_text(encoding="utf-8"))
        age = time.time() - raw.get("fetched_at", 0)
        if age > _CACHE_MAX_AGE_SECONDS:
            logger.info("Benchmark cache expired (%.0f hours old)", age / 3600)
            return None
        models = {k: ModelBenchmarks.from_dict(v) for k, v in raw.get("models", {}).items()}
        logger.info("Loaded %d cached benchmark profiles (%.0f hours old)", len(models), age / 3600)
        return models
    except Exception:
        logger.warning("Failed to load benchmark cache", exc_info=True)
        return None


# ── Public API ────────────────────────────────────────────────────────────

async def refresh_benchmarks(*, force: bool = False) -> Dict[str, ModelBenchmarks]:
    """Fetch fresh benchmark data from external sources and cache locally.

    Returns the merged capability profiles keyed by normalized model name.
    Uses disk cache if available and not expired (7 days).
    """
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    logger.info("Refreshing external benchmark data...")
    lmarena: Dict[str, ModelBenchmarks] = {}
    openllm: Dict[str, ModelBenchmarks] = {}

    # Fetch OpenLLM first (smaller dataset, has the open-weight models we
    # care about most). Then LMArena (larger, may rate-limit).
    try:
        openllm = await fetch_openllm_scores()
    except Exception:
        logger.warning("OpenLLM fetch failed", exc_info=True)

    try:
        lmarena = await fetch_lmarena_scores()
    except Exception:
        logger.warning("LMArena fetch failed", exc_info=True)

    if not lmarena and not openllm:
        # Both failed — try loading stale cache as fallback
        stale = _load_stale_cache()
        if stale:
            logger.warning("Using stale benchmark cache as fallback")
            return stale
        return {}

    merged = _merge_profiles(lmarena, openllm)
    _save_cache(merged)
    return merged


def _load_stale_cache() -> Optional[Dict[str, ModelBenchmarks]]:
    """Load cache regardless of age — better stale data than none."""
    if not _ENRICHED_CACHE.exists():
        return None
    try:
        raw = json.loads(_ENRICHED_CACHE.read_text(encoding="utf-8"))
        return {k: ModelBenchmarks.from_dict(v) for k, v in raw.get("models", {}).items()}
    except Exception:
        return None


def lookup_model(
    model_id: str,
    profiles: Dict[str, ModelBenchmarks],
) -> Optional[ModelBenchmarks]:
    """Find benchmark profile for a model ID using fuzzy alias matching.

    Tries exact match first, then alias-based fuzzy match.
    """
    key = _normalize_model_name(model_id)
    if key in profiles:
        return profiles[key]

    # Try all alias permutations
    aliases = _build_alias_map(model_id)
    for alias in aliases:
        if alias in profiles:
            return profiles[alias]

    # Substring match: "qwen2.5-coder:7b" matches "qwen-qwen2.5-coder-7b-instruct"
    for pkey, profile in profiles.items():
        if key in pkey or any(a in pkey for a in aliases):
            return profile
        # Also check the profile's own aliases
        if any(key in a or a in key for a in profile.aliases):
            return profile

    return None


async def seed_gics_priors(
    gics_service: Any,
    provider_type: str,
    models: List[str],
    profiles: Optional[Dict[str, ModelBenchmarks]] = None,
) -> int:
    """Seed GICS with external benchmark priors for a list of models.

    Returns the number of models successfully seeded.
    """
    if profiles is None:
        profiles = await refresh_benchmarks()
    if not profiles:
        return 0

    seeded = 0
    for model_id in models:
        profile = lookup_model(model_id, profiles)
        if not profile or not profile.dimensions:
            continue

        try:
            gics_service.seed_model_prior(
                provider_type=provider_type,
                model_id=model_id,
                prior_scores=profile.dimensions,
                metadata={
                    "sources": profile.sources,
                    "params_b": profile.params_b,
                    "benchmark_updated_at": profile.updated_at,
                },
            )
            seeded += 1
            logger.debug(
                "Seeded GICS prior for %s/%s: %d dimensions",
                provider_type, model_id, len(profile.dimensions),
            )
        except Exception:
            logger.warning("Failed to seed GICS prior for %s/%s", provider_type, model_id, exc_info=True)

    logger.info(
        "Seeded GICS priors for %d/%d models (provider=%s)",
        seeded, len(models), provider_type,
    )
    return seeded


def get_model_strengths(
    model_id: str,
    profiles: Dict[str, ModelBenchmarks],
    *,
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    """Return the top-N strengths for a model as a sorted list.

    Each entry: {"dimension": str, "score": float, "source": str}
    Useful for UI display and routing hints.
    """
    profile = lookup_model(model_id, profiles)
    if not profile:
        return []
    ranked = sorted(
        profile.dimensions.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return [
        {"dimension": dim, "score": round(score, 3), "source": profile.sources.get(dim, "unknown")}
        for dim, score in ranked[:top_n]
    ]


def get_best_model_for_task(
    task_dimension: str,
    profiles: Dict[str, ModelBenchmarks],
    *,
    candidates: Optional[List[str]] = None,
) -> Optional[str]:
    """Find the best model for a given task dimension among candidates.

    If candidates is None, searches all profiled models.
    Returns the model_id of the best match, or None.
    """
    best_id: Optional[str] = None
    best_score = -1.0

    if candidates:
        for model_id in candidates:
            profile = lookup_model(model_id, profiles)
            if profile and task_dimension in profile.dimensions:
                score = profile.dimensions[task_dimension]
                if score > best_score:
                    best_score = score
                    best_id = model_id
    else:
        for _key, profile in profiles.items():
            if task_dimension in profile.dimensions:
                score = profile.dimensions[task_dimension]
                if score > best_score:
                    best_score = score
                    best_id = profile.model_id

    return best_id
