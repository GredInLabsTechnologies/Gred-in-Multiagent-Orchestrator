import math
import psutil
from typing import Dict, Any
from .hardware_monitor_service import HardwareMonitorService
from .provider_catalog_service import ProviderCatalogService
from .ops_service import OpsService

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
    def _determine_provider_and_reason(cls, gpu_vendor: str, wsl2: bool) -> tuple[str, str]:
        if gpu_vendor == "nvidia" and wsl2:
            return "sglang", "Optimal local inference (NVIDIA + WSL2)"
        elif gpu_vendor == "nvidia":
            return "ollama", "Good local inference (NVIDIA)"
        elif gpu_vendor in ("amd", "intel"):
            return "lm_studio", f"Supported local inference ({gpu_vendor.upper()})"
        return "openai", "Cloud fallback (No compatible GPU found)"

    @classmethod
    def _get_fallback_models(cls, provider: str, vram_gb: float) -> tuple[str, str, float, float]:
        if vram_gb >= 20.0:
            recommended_model = "qwen2.5-coder:32b" if provider == "ollama" else "qwen2.5-coder-32b-instruct"
            worker_model = "qwen2.5-coder:7b" if provider == "ollama" else "qwen2.5-coder-7b-instruct"
            return recommended_model, worker_model, 20.0, 6.0
        
        recommended_model = "qwen2.5-coder:7b" if provider == "ollama" else "qwen2.5-coder-7b-instruct"
        worker_model = "qwen2.5-coder:3b" if provider == "ollama" else "qwen2.5-coder-3b-instruct"
        return recommended_model, worker_model, 6.0, 3.0

    @classmethod
    async def _select_models(cls, provider: str, vram_gb: float) -> tuple[str, str, float, float]:
        if provider == "openai":
            return "gpt-4o", "gpt-4o-mini", 0.0, 0.0

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

        best_orchestrator = max(model_candidates, key=lambda x: x[2])
        best_worker = max(model_candidates, key=lambda x: x[3])
        return best_orchestrator[0].id, best_worker[0].id, best_orchestrator[1], best_worker[1]

    @classmethod
    def _calculate_workers(cls, provider: str, free_vram_gb: float, total_ram: float, cores: int, worker_model_size_gb: float, orchestrator_model_size_gb: float) -> int:
        if provider == "openai":
            return 4 # Cloud concurrency
            
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
        vram_gb = snapshot.get("gpu_vram_gb", 0.0)
        free_vram_gb = snapshot.get("gpu_vram_free_gb", 0.0)
        total_ram = snapshot.get("total_ram_gb", 16.0)
        wsl2 = snapshot.get("wsl2_available", False)
        
        provider, reason = cls._determine_provider_and_reason(gpu_vendor, wsl2)
        
        recommended_model, worker_model, orchestrator_model_size_gb, worker_model_size_gb = await cls._select_models(provider, vram_gb)
        
        cores = psutil.cpu_count(logical=False) or 2
        workers = cls._calculate_workers(provider, free_vram_gb, total_ram, cores, worker_model_size_gb, orchestrator_model_size_gb)
            
        orchestrator = {
            "provider": provider,
            "model": recommended_model,
            "reason": reason,
        }
        workers_reco = [
            {
                "provider": provider,
                "model": worker_model,
                "count_hint": workers,
                "reason": "Throughput balance based on available compute",
            }
        ]

        # Backward-compatible fields are kept (provider/model/workers/reason)
        return {
            "provider": provider,
            "model": recommended_model,
            "workers": workers,
            "reason": reason,
            "hardware": snapshot,
            "orchestrator": orchestrator,
            "worker_pool": workers_reco,
            "topology_reason": reason,
            "hardware_snapshot": snapshot,
        }
