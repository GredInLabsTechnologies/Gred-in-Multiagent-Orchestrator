from typing import Dict, List, Optional, Any
import logging
from .providers.base_provider import BaseProvider
from .providers.ollama_provider import OllamaProvider
from .providers.groq_provider import GroqProvider
from .providers.codex_provider import CodexProvider
from .providers.openrouter_provider import OpenRouterProvider

logger = logging.getLogger("orchestrator.provider_registry")

class ProviderRegistry:
    _providers: Dict[str, BaseProvider] = {}
    
    @classmethod
    def register_provider(cls, config: Dict[str, Any]) -> str:
        """
        Register a new provider from config.
        Config must have 'type' and 'id'.
        Returns provider_id.
        """
        p_type = config.get("type")
        p_id = config.get("id")
        
        if not p_type or not p_id:
            raise ValueError("Provider config must have 'type' and 'id'")
            
        if p_id in cls._providers:
            logger.warning(f"Provider {p_id} already exists. Overwriting.")
            
        provider: Optional[BaseProvider] = None
        
        if p_type == "ollama":
            provider = OllamaProvider(p_id, config)
        elif p_type == "groq":
            provider = GroqProvider(p_id, config)
        elif p_type == "codex":
            provider = CodexProvider(p_id, config)
        elif p_type == "openrouter":
            provider = OpenRouterProvider(p_id, config)
        else:
            raise ValueError(f"Unknown provider type: {p_type}")
            
        cls._providers[p_id] = provider
        logger.info(f"Registered provider: {p_id} ({p_type})")
        return p_id

    @classmethod
    def get_provider(cls, p_id: str) -> Optional[BaseProvider]:
        return cls._providers.get(p_id)

    @classmethod
    def list_providers(cls) -> List[Dict[str, Any]]:
        """Return list of providers with metadata (secrets masked)"""
        results = []
        for p in cls._providers.values():
            # Mask sensitive tokens in config
            safe_config = p.config.copy()
            if "api_key" in safe_config:
                safe_config["api_key"] = "********"
                
            results.append({
                "id": p.provider_id,
                "type": p.provider_type,
                "is_local": p.is_local,
                "config": safe_config
            })
        return results

    @classmethod
    def remove_provider(cls, p_id: str):
        if p_id in cls._providers:
            del cls._providers[p_id]
            logger.info(f"Removed provider: {p_id}")

    @classmethod
    def get_all(cls) -> List[BaseProvider]:
        return list(cls._providers.values())
