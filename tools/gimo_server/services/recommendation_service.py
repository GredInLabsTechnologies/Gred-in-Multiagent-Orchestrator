import math
import psutil
from typing import Dict, Any
from .hardware_monitor_service import HardwareMonitorService
from .provider_catalog_service import ProviderCatalogService

class RecommendationService:
    @classmethod
    async def get_recommendation(cls) -> Dict[str, Any]:
        hw_monitor = HardwareMonitorService.get_instance()
        snapshot = hw_monitor.get_current_state()
        
        gpu_vendor = snapshot.get("gpu_vendor", "none")
        vram_gb = snapshot.get("gpu_vram_gb", 0.0)
        free_vram_gb = snapshot.get("gpu_vram_free_gb", 0.0)
        total_ram = snapshot.get("total_ram_gb", 16.0)
        wsl2 = snapshot.get("wsl2_available", False)
        
        provider = "openai"
        reason = "Cloud fallback (No compatible GPU found)"
        
        # Scoring logic
        if gpu_vendor == "nvidia" and wsl2:
            provider = "sglang"
            reason = "Optimal local inference (NVIDIA + WSL2)"
        elif gpu_vendor == "nvidia":
            provider = "ollama"
            reason = "Good local inference (NVIDIA)"
        elif gpu_vendor in ("amd", "intel"):
            provider = "lm_studio"
            reason = f"Supported local inference ({gpu_vendor.upper()})"
            
        # Model logic
        recommended_model = "gpt-4o"
        model_size_gb = 0.0
        
        if provider != "openai":
            # Map canonical names for provider catalog
            catalog_provider = "ollama_local" if provider == "ollama" else provider
            catalog_models, _ = await ProviderCatalogService.list_available_models(catalog_provider)
            
            # Filter by VRAM budget + coding tag
            model_candidates = []
            
            for m in catalog_models:
                m_size_gb = getattr(m, "size", None)
                try:
                    # attempt to parse size string if available (e.g. "7B" -> ~7.0 GB VRAM required)
                    if m_size_gb and isinstance(m_size_gb, str) and m_size_gb.lower().endswith("b"):
                        m_size_gb = float(m_size_gb.lower().replace("b", ""))
                    else:
                        m_size_gb = 6.0
                except Exception:
                    m_size_gb = 6.0
                    
                is_coding = "coder" in m.id.lower() or "qwen" in m.id.lower() or "llama" in m.id.lower()
                
                if m_size_gb <= vram_gb and is_coding:
                    # Score based on size (larger is better quality, assuming fits in VRAM)
                    model_candidates.append((m, m_size_gb))
                    
            if model_candidates:
                # Sort by quality (approximated by size) descending
                model_candidates.sort(key=lambda x: x[1], reverse=True)
                best_match = model_candidates[0]
                recommended_model = best_match[0].id
                model_size_gb = best_match[1]
            else:
                # Fallback if no matching models found in catalog
                if vram_gb >= 20.0:
                    recommended_model = "qwen2.5-coder:32b" if provider == "ollama" else "qwen2.5-coder-32b-instruct"
                    model_size_gb = 20.0
                else:
                    recommended_model = "qwen2.5-coder:7b" if provider == "ollama" else "qwen2.5-coder-7b-instruct"
                    model_size_gb = 6.0
                    
        # Worker calculation
        cores = psutil.cpu_count(logical=False) or 2
        
        if provider != "openai":
            w_vram = math.floor(free_vram_gb / model_size_gb) if model_size_gb > 0 else 1
            w_ram = math.floor(total_ram / 2.0)
            w_cpu = math.floor(cores / 2.0)
            workers = max(1, int(min(w_vram, w_ram, w_cpu)))
        else:
            workers = 4 # Cloud concurrency
            
        return {
            "provider": provider,
            "model": recommended_model,
            "workers": workers,
            "reason": reason,
            "hardware": snapshot
        }
