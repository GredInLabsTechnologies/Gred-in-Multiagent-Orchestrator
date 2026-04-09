"""Hardware-aware provider recommendation engine.

Approach mirrors game auto-detect systems: score each hardware component
against reference tiers, identify the bottleneck, then pick the best
provider/model combination within those constraints.

Key insight (2025 LLM hardware research): memory bandwidth is the primary
limiter for LLM inference — not raw compute. VRAM size dictates which models
are feasible; CPU RAM enables CPU-offload fallback; NPU is still experimental
for LLMs (DirectML) but worth detecting for future routing.
"""
from __future__ import annotations

import math
import shutil
import psutil
from typing import Any, Dict, NamedTuple

from .hardware_monitor_service import HardwareMonitorService
from .providers.catalog_service import ProviderCatalogService
from .ops_service import OpsService


# ── Scoring tables (0-100 per component) ─────────────────────────────────────
# Based on practical VRAM requirements for quantised LLM models (Q4_K_M):
#   3B  ≈ 2.0 GB   7B  ≈ 4.5 GB   13B ≈ 8 GB
#   34B ≈ 20 GB    70B ≈ 40 GB
#
# Scoring mirrors game auto-detect: each breakpoint maps to a "preset tier".

def _score_vram(vram_gb: float) -> float:
    """Primary constraint. Returns 0-40."""
    if vram_gb >= 24.0: return 40.0
    if vram_gb >= 16.0: return 35.0
    if vram_gb >= 12.0: return 28.0
    if vram_gb >=  8.0: return 20.0
    if vram_gb >=  6.0: return 14.0
    if vram_gb >=  4.0: return  6.0   # marginal — iGPU shared memory
    if vram_gb >=  2.0: return  2.0
    return 0.0


def _score_ram(ram_gb: float, unified_memory: bool = False) -> float:
    """CPU-offload / unified memory capacity. Returns 0-25.

    Unified memory (APU/SoC) gets a bonus because the iGPU can access full
    RAM as VRAM — memory bandwidth is higher than discrete DDR4.
    """
    base: float
    if ram_gb >= 64.0: base = 25.0
    elif ram_gb >= 32.0: base = 18.0
    elif ram_gb >= 24.0: base = 15.0
    elif ram_gb >= 16.0: base = 10.0
    elif ram_gb >=  8.0: base =  4.0
    else: base = 0.0
    # Unified memory bonus: iGPU can use all RAM as VRAM (e.g. ROG Ally, Mac M-series)
    return min(25.0, base + (4.0 if unified_memory else 0.0))


def _score_cpu(cores: int) -> float:
    """CPU inference throughput. Returns 0-20."""
    if cores >= 16: return 20.0
    if cores >= 12: return 16.0
    if cores >=  8: return 12.0
    if cores >=  6: return  8.0
    if cores >=  4: return  5.0
    return 2.0


def _score_npu(npu_vendor: str, npu_tops: float) -> float:
    """NPU bonus (future routing signal). Returns 0-5."""
    if npu_vendor in ("none", "") or npu_tops <= 0:
        return 0.0
    if npu_tops >= 40:  return 5.0   # Strix Halo, future
    if npu_tops >= 16:  return 3.0   # Z1 Extreme, Phoenix
    return 1.5


def _score_installed_cli() -> float:
    """Bonus for having CLI providers ready to use. Returns 0-10."""
    score = 0.0
    if shutil.which("codex") is not None:
        score += 7.0   # Higher weight: already authenticated + full account access
    if shutil.which("claude") is not None:
        score += 3.0
    return min(score, 10.0)


# ── Hardware tier ─────────────────────────────────────────────────────────────

class HardwareTier(NamedTuple):
    name: str          # "cloud_only" | "cloud_preferred" | "light_local" | "medium_local" | "heavy_local"
    label: str         # Human-readable Spanish label
    total_score: float
    vram_score: float
    ram_score: float
    bottleneck: str    # Which component is the limiting factor


def _classify_tier(
    vram_gb: float,
    ram_gb: float,
    cores: int,
    gpu_vendor: str,
    npu_vendor: str,
    npu_tops: float,
    unified_memory: bool = False,
    cpu_inference_capable: bool = False,
) -> HardwareTier:
    vs = _score_vram(vram_gb)
    rs = _score_ram(ram_gb, unified_memory=unified_memory)
    cs = _score_cpu(cores)
    ns = _score_npu(npu_vendor, npu_tops)
    cli = _score_installed_cli()

    # Weight: VRAM is king, then RAM (CPU offload), then CPU throughput
    total = vs + rs + cs + ns + cli

    # Bottleneck detection — consider CPU inference path too
    is_igpu = gpu_vendor in ("amd", "intel") and vram_gb < 6.0
    if is_igpu and unified_memory:
        # APU with unified memory: iGPU uses RAM as VRAM
        # Effective "VRAM" for inference = RAM (at lower bandwidth)
        effective_vram = min(ram_gb * 0.6, 16.0)  # can dedicate up to 60% RAM as VRAM
        vs = max(vs, _score_vram(effective_vram) * 0.75)  # 75% efficiency vs dedicated GPU

    if vs < 6.0 and rs < 10.0 and not cpu_inference_capable:
        bottleneck = "VRAM+RAM insuficientes para inferencia local"
    elif vs < 6.0 and cpu_inference_capable:
        bottleneck = "Sin VRAM dedicada — CPU inference posible (llama.cpp) con modelos ≤7B Q4"
    elif vs < 6.0:
        bottleneck = "VRAM limitada — CPU-offload recomendado"
    elif vs < 14.0:
        bottleneck = "VRAM limita modelos a ≤7B (Q4)"
    elif vs < 28.0:
        bottleneck = "VRAM limita modelos a ≤13B (Q4)"
    else:
        bottleneck = "Sin cuello de botella significativo"

    # Shared iGPU penalty (unless unified memory APU — they're different)
    if is_igpu and not unified_memory:
        total = max(0.0, total - 8.0)

    if total >= 75:
        return HardwareTier("heavy_local", "Alto rendimiento local", total, vs, rs, bottleneck)
    if total >= 50:
        return HardwareTier("medium_local", "Rendimiento local moderado", total, vs, rs, bottleneck)
    if total >= 30:
        return HardwareTier("light_local", "Inferencia local ligera (modelos pequeños)", total, vs, rs, bottleneck)
    if total >= 15:
        return HardwareTier("cloud_preferred", "Cloud recomendado (hardware limitado)", total, vs, rs, bottleneck)
    return HardwareTier("cloud_only", "Sólo cloud (sin hardware local compatible)", total, vs, rs, bottleneck)


# ── Provider selection per tier ───────────────────────────────────────────────

_CLOUD_CLI_MODELS: Dict[str, tuple[str, str]] = {
    "codex":  ("gpt-5-codex", "gpt-4.1-mini"),
    "claude": ("claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"),
    "openai": ("gpt-4o", "gpt-4o-mini"),
}

_LOCAL_PROVIDER_PRIORITY = [
    # (gpu_vendor_match, wsl2_required, provider_id)
    ("nvidia", True,  "sglang"),
    ("nvidia", False, "ollama"),
    ("amd",    False, "lm_studio"),
    ("intel",  False, "lm_studio"),
]


def _select_provider_for_tier(
    tier: HardwareTier,
    gpu_vendor: str,
    wsl2: bool,
    npu_vendor: str,
    npu_tops: float,
    unified_memory: bool = False,
    cpu_inference_capable: bool = False,
) -> tuple[str, str]:
    """Returns (provider_id, reason_str)."""

    has_npu = npu_vendor not in ("none", "") and npu_tops > 0
    npu_note = (
        f" NPU {npu_vendor} ({npu_tops:.0f} TOPS) detectada — "
        "útil para inferencia ≤3B via DirectML (experimental)."
    ) if has_npu else ""

    # Heavy/medium local: use GPU provider if compatible
    if tier.name in ("heavy_local", "medium_local"):
        for vendor_match, needs_wsl2, pid in _LOCAL_PROVIDER_PRIORITY:
            if gpu_vendor == vendor_match and (not needs_wsl2 or wsl2):
                label = {
                    "sglang": "sglang (NVIDIA+WSL2)",
                    "ollama": "Ollama (NVIDIA GPU)",
                    "lm_studio": f"LM Studio ({gpu_vendor.upper()} GPU)",
                }.get(pid, pid)
                return pid, f"Hardware local suficiente. {label} recomendado. {tier.bottleneck}."

        # APU with unified memory in medium/heavy: lm_studio via iGPU+RAM
        if unified_memory and tier.name == "medium_local":
            return "lm_studio", (
                f"APU con memoria unificada ({gpu_vendor.upper()}). "
                f"LM Studio puede usar iGPU+RAM como VRAM dinámica. {tier.bottleneck}.{npu_note}"
            )

    # Light local
    if tier.name == "light_local":
        if gpu_vendor == "nvidia":
            return "ollama", f"Inferencia local ligera vía Ollama (NVIDIA). Modelos ≤7B Q4. {tier.bottleneck}."
        if unified_memory and cpu_inference_capable:
            # APU like ROG Ally: llama.cpp CPU inference is viable
            return "lm_studio", (
                f"APU {gpu_vendor.upper()} con memoria unificada. "
                f"LM Studio (CPU+iGPU) puede correr modelos ≤7B Q4 a velocidad aceptable. "
                f"{tier.bottleneck}.{npu_note}"
            )
        if cpu_inference_capable:
            return "llama-cpp", (
                f"Sin GPU dedicada pero CPU con RAM suficiente para llama.cpp. "
                f"Modelos ≤7B Q4 en CPU-only. {tier.bottleneck}.{npu_note}"
            )

    # cloud_preferred / cloud_only: pick best installed CLI
    if shutil.which("codex") is not None:
        return "codex", (
            f"Hardware local insuficiente para inferencia LLM estable. "
            f"{tier.bottleneck}. "
            f"Codex CLI instalado — orquestador cloud de menor fricción.{npu_note}"
        )
    if shutil.which("claude") is not None:
        return "claude", (
            f"Hardware local insuficiente. {tier.bottleneck}. "
            f"Claude CLI instalado.{npu_note}"
        )
    return "openai", (
        f"Sin hardware local ni CLI instalado. Fallback a OpenAI API. {tier.bottleneck}.{npu_note}"
    )


# ── Model selection ───────────────────────────────────────────────────────────

class RecommendationService:
    @staticmethod
    def _parse_model_size_gb(raw_size: Any, default: float = 6.0) -> float:
        try:
            if isinstance(raw_size, (int, float)):
                return max(0.5, float(raw_size))
            if isinstance(raw_size, str):
                value = raw_size.strip().lower()
                if value.endswith("gb"):
                    return max(0.5, float(value.replace("gb", "").strip()))
                if value.endswith("b"):
                    return max(0.5, float(value.replace("b", "").strip()))
        except Exception:
            pass
        return default

    @staticmethod
    def _model_capability_tags(model: Any) -> set[str]:
        caps = getattr(model, "capabilities", None)
        if not isinstance(caps, list):
            caps = []
        bag = {str(c).strip().lower() for c in caps if str(c).strip()}
        mid = str(getattr(model, "id", "") or "").lower()
        if any(k in mid for k in ("coder", "codex", "code")):
            bag.add("code")
        if any(k in mid for k in ("reason", "think", "o1", "r1")):
            bag.add("reasoning")
        return bag

    @classmethod
    def _reliability_for(cls, provider_type: str, model_id: str) -> Dict[str, Any]:
        rel = OpsService.get_model_reliability(provider_type=provider_type, model_id=model_id) or {}
        score = float(rel.get("score", 0.5) or 0.5)
        anomaly = bool(rel.get("anomaly", False))
        return {"score": max(0.0, min(1.0, score)), "anomaly": anomaly}

    @classmethod
    def _models_for_cloud_provider(cls, provider: str) -> tuple[str, str, float, float]:
        orch, worker = _CLOUD_CLI_MODELS.get(provider, ("gpt-4o", "gpt-4o-mini"))
        return orch, worker, 0.0, 0.0

    @classmethod
    def _get_fallback_models(cls, provider: str, vram_gb: float) -> tuple[str, str, float, float]:
        if vram_gb >= 20.0:
            orch = "qwen2.5-coder:32b" if provider == "ollama" else "qwen2.5-coder-32b-instruct"
            worker = "qwen2.5-coder:7b" if provider == "ollama" else "qwen2.5-coder-7b-instruct"
            return orch, worker, 20.0, 6.0
        orch = "qwen2.5-coder:7b" if provider == "ollama" else "qwen2.5-coder-7b-instruct"
        worker = "qwen2.5-coder:3b" if provider == "ollama" else "qwen2.5-coder-3b-instruct"
        return orch, worker, 6.0, 3.0

    @classmethod
    async def _select_models(cls, provider: str, vram_gb: float) -> tuple[str, str, float, float]:
        cloud_providers = {"openai", "codex", "claude", "anthropic"}
        if provider in cloud_providers:
            return cls._models_for_cloud_provider(provider)

        catalog_provider = "ollama_local" if provider == "ollama" else provider
        catalog_models, _ = await ProviderCatalogService.list_available_models(catalog_provider)

        model_candidates = []
        for m in catalog_models:
            m_size_gb = cls._parse_model_size_gb(getattr(m, "size", None), default=6.0)
            if m_size_gb > max(vram_gb, 0.5):
                continue
            caps = cls._model_capability_tags(m)
            if "code" not in caps and not any(k in str(m.id).lower() for k in ("qwen", "llama", "code", "coder")):
                continue
            reliability = cls._reliability_for(catalog_provider, str(m.id))
            if reliability["anomaly"]:
                continue

            reasoning_boost = 1.0 if "reasoning" in caps else 0.0
            coding_boost = 0.6 if "code" in caps else 0.0
            orch_score = (m_size_gb * 0.08) + (reasoning_boost * 0.6) + (coding_boost * 0.2) + (reliability["score"] * 0.7)
            throughput = 1.0 / max(1.0, m_size_gb)
            worker_score = (throughput * 1.2) + (coding_boost * 0.7) + (reliability["score"] * 0.5)
            model_candidates.append((m, m_size_gb, orch_score, worker_score))

        if not model_candidates:
            return cls._get_fallback_models(provider, vram_gb)

        best_orch = max(model_candidates, key=lambda x: x[2])
        best_worker = max(model_candidates, key=lambda x: x[3])
        return best_orch[0].id, best_worker[0].id, best_orch[1], best_worker[1]

    @classmethod
    def _calculate_workers(
        cls, provider: str, free_vram_gb: float, total_ram: float,
        cores: int, worker_model_size_gb: float, orchestrator_model_size_gb: float,
    ) -> int:
        cloud_providers = {"openai", "codex", "claude", "anthropic"}
        if provider in cloud_providers:
            # Cloud: concurrency limited by rate limits, not hardware
            return 4
        effective_worker_size = worker_model_size_gb or orchestrator_model_size_gb
        w_vram = math.floor(free_vram_gb / effective_worker_size) if effective_worker_size > 0 else 1
        w_ram = math.floor(total_ram / 2.0)
        w_cpu = math.floor(cores / 2.0)
        return max(1, int(min(w_vram, w_ram, w_cpu)))

    @classmethod
    async def get_recommendation(cls) -> Dict[str, Any]:
        hw_monitor = HardwareMonitorService.get_instance()
        snapshot = hw_monitor.get_current_state()

        gpu_vendor = snapshot.get("gpu_vendor", "none")
        vram_gb = float(snapshot.get("gpu_vram_gb", 0.0))
        free_vram_gb = float(snapshot.get("gpu_vram_free_gb", 0.0))
        total_ram = float(snapshot.get("total_ram_gb", 16.0))
        wsl2 = bool(snapshot.get("wsl2_available", False))
        npu_vendor = str(snapshot.get("npu_vendor", "none"))
        npu_tops = float(snapshot.get("npu_tops", 0.0))
        unified_memory = bool(snapshot.get("unified_memory", False))
        cpu_inference_capable = bool(snapshot.get("cpu_inference_capable", False))
        cores = psutil.cpu_count(logical=False) or 2

        # ── Score and classify ────────────────────────────────────────────────
        tier = _classify_tier(
            vram_gb, total_ram, cores, gpu_vendor, npu_vendor, npu_tops,
            unified_memory=unified_memory, cpu_inference_capable=cpu_inference_capable,
        )
        provider, reason = _select_provider_for_tier(
            tier, gpu_vendor, wsl2, npu_vendor, npu_tops,
            unified_memory=unified_memory, cpu_inference_capable=cpu_inference_capable,
        )

        # ── Model selection ───────────────────────────────────────────────────
        orch_model, worker_model, orch_size_gb, worker_size_gb = await cls._select_models(provider, vram_gb)
        workers = cls._calculate_workers(provider, free_vram_gb, total_ram, cores, worker_size_gb, orch_size_gb)

        orchestrator = {"provider": provider, "model": orch_model, "reason": reason}
        workers_reco = [{
            "provider": provider,
            "model": worker_model,
            "count_hint": workers,
            "reason": f"Balance throughput basado en hardware disponible ({tier.label})",
        }]

        # ── Scoring breakdown (exposed for UI) ───────────────────────────────
        scoring = {
            "total": round(tier.total_score, 1),
            "tier": tier.name,
            "tier_label": tier.label,
            "bottleneck": tier.bottleneck,
            "vram_score": round(tier.vram_score, 1),
            "ram_score": round(tier.ram_score, 1),
            "npu_detected": npu_vendor not in ("none", "") and npu_tops > 0,
        }

        return {
            # Backward-compatible fields
            "provider": provider,
            "model": orch_model,
            "workers": workers,
            "reason": reason,
            "hardware": snapshot,
            "orchestrator": orchestrator,
            "worker_pool": workers_reco,
            "topology_reason": reason,
            "hardware_snapshot": snapshot,
            # New scoring detail
            "scoring": scoring,
        }
