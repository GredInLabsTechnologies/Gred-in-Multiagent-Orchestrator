"""Model Recommendation Engine — hardware-aware GGUF model scoring.

Scores each model against a device's real hardware capabilities and returns:
- Fit level (optimal / comfortable / tight / overload)
- Estimated RAM usage, tokens/sec, battery drain
- Recommended device mode (inference / hybrid / utility)
- Impact warnings

RAM formula (industry standard from llama.cpp):
    RAM_GB = (params_B × bits_per_weight / 8) × 1.2 + context_overhead_GB

Token speed estimates based on published mobile benchmarks:
    - Snapdragon 8 Gen 2+: ~15-25 tok/s for 3B q4
    - Snapdragon 6xx: ~5-10 tok/s for 3B q4
    - Exynos 990 (S10): ~8-12 tok/s for 3B q4
    - Older SoCs: ~2-5 tok/s for 3B q4

Sources:
    - llama.cpp quantize README (bits/weight table)
    - arxiv.org/html/2410.03613v3 (mobile LLM benchmarks)
    - ggufloader.github.io/gguf-memory-calculator.html
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("orchestrator.mesh.model_recommendation")


# ── Quantization metadata ─────────────────────────────────────

# Bits per weight for common GGUF quantization types
QUANT_BITS: Dict[str, float] = {
    "q2_k": 2.97, "q2_k_s": 2.97,
    "iq3_xxs": 3.25, "q3_k_s": 3.50, "q3_k_m": 4.00, "q3_k_l": 4.30,
    "iq4_xs": 4.25, "q4_0": 4.50, "q4_k_s": 4.50, "q4_k_m": 4.89, "q4_1": 5.00,
    "q5_0": 5.50, "q5_k_s": 5.50, "q5_k_m": 5.70, "q5_1": 6.00,
    "q6_k": 6.56,
    "q8_0": 8.50,
    "f16": 16.0,
}

# Quality tier (higher = better quality, more resources)
QUANT_QUALITY: Dict[str, int] = {
    "q2_k": 1, "q2_k_s": 1, "iq3_xxs": 2,
    "q3_k_s": 3, "q3_k_m": 4, "q3_k_l": 4,
    "iq4_xs": 5, "q4_0": 5, "q4_k_s": 5, "q4_k_m": 6, "q4_1": 6,
    "q5_0": 7, "q5_k_s": 7, "q5_k_m": 8, "q5_1": 8,
    "q6_k": 9, "q8_0": 10, "f16": 10,
}

# Default context window overhead in GB
_CONTEXT_OVERHEAD_GB = 0.3  # ~2048 tokens context


class FitLevel(str, Enum):
    """How well a model fits the device hardware."""
    optimal = "optimal"          # Runs great, plenty of headroom
    comfortable = "comfortable"  # Runs well, some headroom
    tight = "tight"              # Will work but device may slow down
    overload = "overload"        # Exceeds device capabilities


@dataclass
class ModelRecommendation:
    """Full recommendation for a model on a specific device."""
    model_id: str
    fit_level: FitLevel = FitLevel.comfortable
    recommended: bool = False
    recommended_mode: str = "inference"  # inference / hybrid / utility

    # Resource estimates
    estimated_ram_gb: float = 0.0
    device_ram_gb: float = 0.0
    ram_headroom_pct: float = 0.0         # % of RAM left for OS/apps
    estimated_tokens_per_sec: float = 0.0
    estimated_battery_drain_pct_hr: float = 0.0
    storage_required_gb: float = 0.0
    device_storage_free_gb: float = 0.0

    # Scoring
    score: int = 0                        # 0-100, higher = better fit
    quality_tier: int = 0                 # 1-10 from quantization

    # Impact description
    impact: str = ""                      # Human-readable impact summary
    warnings: List[str] = field(default_factory=list)
    recommendation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "fit_level": self.fit_level.value,
            "recommended": self.recommended,
            "recommended_mode": self.recommended_mode,
            "score": self.score,
            "quality_tier": self.quality_tier,
            "estimated_ram_gb": round(self.estimated_ram_gb, 2),
            "device_ram_gb": round(self.device_ram_gb, 2),
            "ram_headroom_pct": round(self.ram_headroom_pct, 1),
            "estimated_tokens_per_sec": round(self.estimated_tokens_per_sec, 1),
            "estimated_battery_drain_pct_hr": round(self.estimated_battery_drain_pct_hr, 1),
            "storage_required_gb": round(self.storage_required_gb, 2),
            "device_storage_free_gb": round(self.device_storage_free_gb, 2),
            "impact": self.impact,
            "warnings": self.warnings,
            "recommendation_reason": self.recommendation_reason,
        }


# ── SoC performance profiles ──────────────────────────────────

# Base tokens/sec for a 3B q4_k_m model, scaled by actual model size
_SOC_PERF: Dict[str, float] = {
    # Flagship (2023+)
    "snapdragon 8 gen 3": 25.0,
    "snapdragon 8 gen 2": 20.0,
    "snapdragon 8 gen 1": 16.0,
    "dimensity 9300": 24.0,
    "dimensity 9200": 18.0,
    "exynos 2400": 18.0,
    "exynos 2200": 14.0,
    "tensor g4": 20.0,
    "tensor g3": 16.0,
    # Mid-range
    "snapdragon 7 gen": 12.0,
    "snapdragon 778": 11.0,
    "snapdragon 750": 9.0,
    "dimensity 8300": 14.0,
    "dimensity 7200": 10.0,
    "exynos 1380": 8.0,
    # Older flagship
    "snapdragon 865": 10.0,
    "snapdragon 855": 8.0,
    "exynos 9820": 8.0,    # Galaxy S10
    "exynos 990": 10.0,    # Galaxy S20
    # Budget
    "snapdragon 6 gen": 7.0,
    "snapdragon 680": 5.0,
    "helio g99": 5.0,
    "exynos 850": 3.0,
}

# Battery drain (% per hour) for sustained inference on a 3B q4 model
_SOC_DRAIN: Dict[str, float] = {
    "snapdragon 8 gen 3": 12.0, "snapdragon 8 gen 2": 14.0,
    "snapdragon 8 gen 1": 18.0, "dimensity 9300": 11.0,
    "exynos 2400": 15.0, "exynos 9820": 20.0, "exynos 990": 17.0,
    "snapdragon 855": 18.0, "snapdragon 865": 16.0,
}
_DEFAULT_DRAIN = 15.0  # % per hour for unknown SoCs


def _parse_params_b(params_str: str) -> float:
    """Parse '3b', '0.5B', '7b', '13B' → float billion."""
    if not params_str:
        return 0.0
    s = params_str.lower().strip()
    s = s.rstrip("bm")
    try:
        val = float(s)
        # If original string had 'm' (million), convert
        if params_str.lower().endswith("m"):
            return val / 1000.0
        return val
    except ValueError:
        return 0.0


def _lookup_soc_perf(soc_model: str) -> float:
    """Find base tok/s for a SoC by fuzzy matching."""
    soc = soc_model.lower().strip()
    for key, val in _SOC_PERF.items():
        if key in soc:
            return val
    return 6.0  # Conservative default for unknown SoCs


def _lookup_soc_drain(soc_model: str) -> float:
    """Find battery drain %/hr for a SoC."""
    soc = soc_model.lower().strip()
    for key, val in _SOC_DRAIN.items():
        if key in soc:
            return val
    return _DEFAULT_DRAIN


def score_model(
    model_id: str,
    params_str: str,
    quant_str: str,
    size_bytes: int,
    ram_total_mb: int,
    storage_free_mb: int,
    cpu_cores: int = 4,
    soc_model: str = "",
    has_gpu_compute: bool = False,
) -> ModelRecommendation:
    """Score a single model against device hardware.

    Returns a ModelRecommendation with fit level, resource estimates,
    impact description, and warnings.
    """
    rec = ModelRecommendation(model_id=model_id)

    params_b = _parse_params_b(params_str)
    quant = quant_str.lower().strip()
    bits = QUANT_BITS.get(quant, 4.89)  # Default to q4_k_m if unknown
    rec.quality_tier = QUANT_QUALITY.get(quant, 6)

    device_ram_gb = ram_total_mb / 1024.0
    device_storage_gb = storage_free_mb / 1024.0
    rec.device_ram_gb = device_ram_gb
    rec.device_storage_free_gb = device_storage_gb
    rec.storage_required_gb = size_bytes / (1024 ** 3)

    # ── RAM estimation ────────────────────────────────────────
    if params_b > 0:
        model_ram_gb = (params_b * bits / 8) * 1.2 + _CONTEXT_OVERHEAD_GB
    else:
        # Fallback: estimate from file size (model weights ~= file size)
        model_ram_gb = (size_bytes / (1024 ** 3)) * 1.2 + _CONTEXT_OVERHEAD_GB

    rec.estimated_ram_gb = model_ram_gb

    # Android reserves ~1.5-2GB for OS + background apps
    os_reserved_gb = min(2.0, device_ram_gb * 0.35)
    available_ram_gb = device_ram_gb - os_reserved_gb
    rec.ram_headroom_pct = ((available_ram_gb - model_ram_gb) / device_ram_gb) * 100.0

    # ── Token speed estimation ────────────────────────────────
    base_tps = _lookup_soc_perf(soc_model)
    if has_gpu_compute:
        base_tps *= 1.3  # GPU acceleration bonus

    # Scale by model size relative to 3B reference
    if params_b > 0:
        size_factor = 3.0 / max(params_b, 0.5)
    else:
        size_factor = 1.0
    # Scale by quantization (lower bits = faster)
    quant_factor = 4.89 / max(bits, 2.0)
    # Thread scaling (diminishing returns after 4)
    thread_factor = min(cpu_cores, 4) / 4.0

    rec.estimated_tokens_per_sec = base_tps * size_factor * quant_factor * thread_factor

    # ── Battery drain estimation ──────────────────────────────
    base_drain = _lookup_soc_drain(soc_model)
    # Larger models drain more, scale linearly
    drain_factor = max(params_b, 1.0) / 3.0
    rec.estimated_battery_drain_pct_hr = base_drain * drain_factor

    # ── Fit level ─────────────────────────────────────────────
    ram_ratio = model_ram_gb / max(available_ram_gb, 0.1)
    storage_ok = rec.storage_required_gb < device_storage_gb * 0.8

    if ram_ratio <= 0.50 and storage_ok:
        rec.fit_level = FitLevel.optimal
    elif ram_ratio <= 0.75 and storage_ok:
        rec.fit_level = FitLevel.comfortable
    elif ram_ratio <= 0.95 and storage_ok:
        rec.fit_level = FitLevel.tight
    else:
        rec.fit_level = FitLevel.overload

    # ── Score (0-100) ─────────────────────────────────────────
    # When device has headroom, prefer bigger/better models (quality).
    # When device is constrained, prefer smaller/faster models (fit).
    fit_score = max(0, 100 - int(ram_ratio * 100))
    quality_score = rec.quality_tier * 10
    speed_score = min(30, int(rec.estimated_tokens_per_sec * 2))
    # Model capability score: bigger params = more capable (log scale)
    import math
    capability_score = min(40, int(math.log2(max(params_b, 0.25) + 1) * 15))

    if rec.fit_level in (FitLevel.optimal, FitLevel.comfortable):
        # Plenty of room → prioritize capability and quality
        rec.score = int(capability_score * 0.4 + quality_score * 0.3 + fit_score * 0.2 + speed_score * 0.1)
    else:
        # Tight/overload → prioritize fit and speed
        rec.score = int(fit_score * 0.5 + speed_score * 0.2 + quality_score * 0.2 + capability_score * 0.1)
    rec.score = max(0, min(100, rec.score))

    # ── Mode recommendation ───────────────────────────────────
    if rec.fit_level == FitLevel.overload:
        rec.recommended_mode = "utility"
    elif rec.fit_level == FitLevel.tight:
        rec.recommended_mode = "hybrid"
    else:
        rec.recommended_mode = "inference"

    # ── Impact description ────────────────────────────────────
    if rec.fit_level == FitLevel.optimal:
        rec.impact = (
            f"Excellent. Model uses {rec.estimated_ram_gb:.1f} GB of "
            f"{device_ram_gb:.0f} GB available. Estimated performance: "
            f"~{rec.estimated_tokens_per_sec:.0f} tok/s. "
            f"Device will run normally."
        )
    elif rec.fit_level == FitLevel.comfortable:
        rec.impact = (
            f"Good. Model uses {rec.estimated_ram_gb:.1f} GB of "
            f"{device_ram_gb:.0f} GB. Performance: ~{rec.estimated_tokens_per_sec:.0f} tok/s. "
            f"May notice slight slowdown in other apps during inference."
        )
    elif rec.fit_level == FitLevel.tight:
        rec.impact = (
            f"Tight. Model needs {rec.estimated_ram_gb:.1f} GB and "
            f"device has {device_ram_gb:.0f} GB. Performance: "
            f"~{rec.estimated_tokens_per_sec:.0f} tok/s. "
            f"Hybrid mode recommended. Background apps will be killed."
        )
    else:
        rec.impact = (
            f"Overload. Model needs {rec.estimated_ram_gb:.1f} GB but only "
            f"{available_ram_gb:.1f} GB available. Device will experience "
            f"instability, force-closes, and thermal throttling. "
            f"Run at your own risk."
        )

    # ── Warnings ──────────────────────────────────────────────
    if rec.fit_level == FitLevel.overload:
        rec.warnings.append("Insufficient RAM — Android will aggressively kill background apps")
    if rec.ram_headroom_pct < 10:
        rec.warnings.append(f"Only {rec.ram_headroom_pct:.0f}% RAM free during inference")
    if rec.estimated_battery_drain_pct_hr > 20:
        rec.warnings.append(f"High drain: ~{rec.estimated_battery_drain_pct_hr:.0f}%/hour battery")
    if not storage_ok:
        rec.warnings.append(f"Insufficient storage: needs {rec.storage_required_gb:.1f} GB, free: {device_storage_gb:.1f} GB")
    if rec.estimated_tokens_per_sec < 3:
        rec.warnings.append("Very slow (<3 tok/s) — degraded experience")
    if params_b >= 7 and ram_total_mb < 8192:
        rec.warnings.append("7B+ models not recommended on devices with <8 GB RAM")

    return rec


def recommend_models(
    models: list,
    ram_total_mb: int,
    storage_free_mb: int,
    cpu_cores: int = 4,
    soc_model: str = "",
    has_gpu_compute: bool = False,
) -> List[ModelRecommendation]:
    """Score all models and select the best recommendation.

    Args:
        models: List of ModelInfo objects (model_id, params, quantization, size_bytes)
        ram_total_mb: Device total RAM in MB
        storage_free_mb: Device free storage in MB
        cpu_cores: Number of CPU cores
        soc_model: SoC model string (e.g. "Exynos 9820")
        has_gpu_compute: Whether device has usable GPU compute

    Returns:
        List of ModelRecommendation sorted by score (best first),
        with the top pick marked as recommended=True.
    """
    recs = []
    for m in models:
        rec = score_model(
            model_id=m.model_id,
            params_str=m.params,
            quant_str=m.quantization,
            size_bytes=m.size_bytes,
            ram_total_mb=ram_total_mb,
            storage_free_mb=storage_free_mb,
            cpu_cores=cpu_cores,
            soc_model=soc_model,
            has_gpu_compute=has_gpu_compute,
        )
        recs.append(rec)

    # Sort by score descending
    recs.sort(key=lambda r: r.score, reverse=True)

    # Mark the best non-overload model as recommended
    for rec in recs:
        if rec.fit_level != FitLevel.overload:
            rec.recommended = True
            rec.recommendation_reason = _build_reason(rec)
            break
    else:
        # All overload — recommend the least bad one but warn
        if recs:
            recs[0].recommended = True
            recs[0].recommendation_reason = (
                "No model fits comfortably on this device. "
                "Utility mode recommended (no local inference)."
            )

    return recs


def _build_reason(rec: ModelRecommendation) -> str:
    """Build human-readable recommendation reason."""
    parts = []
    if rec.fit_level == FitLevel.optimal:
        parts.append("Best performance/quality balance for this hardware")
    elif rec.fit_level == FitLevel.comfortable:
        parts.append("Good balance with sufficient RAM headroom")
    elif rec.fit_level == FitLevel.tight:
        parts.append("Functional but tight — consider hybrid mode")

    parts.append(f"~{rec.estimated_tokens_per_sec:.0f} tok/s estimated")
    parts.append(f"~{rec.estimated_battery_drain_pct_hr:.0f}%/hour battery")

    if rec.quality_tier >= 7:
        parts.append("high quality")
    elif rec.quality_tier >= 5:
        parts.append("good quality")
    else:
        parts.append("basic quality (aggressive compression)")

    return ". ".join(parts) + "."
