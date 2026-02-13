import logging
from typing import AsyncGenerator, Optional
from tools.repo_orchestrator.services.providers.base_provider import BaseProvider
from tools.repo_orchestrator.services.provider_registry import ProviderRegistry
from tools.repo_orchestrator.services.model_router import ModelRouter

logger = logging.getLogger("orchestrator.model_service")

class ModelService:
    """
    Unified interface for AI model generation.
    Routes requests via ModelRouter to the appropriate Provider.
    """
    
    _legacy_default: Optional[BaseProvider] = None

    @classmethod
    def initialize(cls, provider_type: str = "ollama", **kwargs):
        """
        Legacy init. We now prefer using ProviderRegistry directly,
        but we can set up a default fallback here.
        """
        if provider_type == "ollama":
            from tools.repo_orchestrator.services.providers.ollama_provider import OllamaProvider
            # Register as a provider if not exists?
            # For now just keep a reference for extreme fallback
            cls._legacy_default = OllamaProvider("default-ollama", {"base_url": kwargs.get("base_url", "http://localhost:11434")})

    @classmethod
    async def generate(cls, prompt: str, model: str = "default", **kwargs) -> str:
        """
        Generate text.
        1. Ask ModelRouter for best provider/model.
        2. Use that provider.
        """
        try:
            # Route based on prompt content
            provider, routed_model = ModelRouter.select_provider(prompt)
            
            if provider:
                # If model is 'default', use routed_model
                final_model = routed_model if model == "default" else model
                return await provider.generate(prompt, final_model, **kwargs)
                
        except Exception as e:
            logger.error(f"Routing failed: {e}")

        # Fallback
        if cls._legacy_default:
            return await cls._legacy_default.generate(prompt, model, **kwargs)
            
        raise RuntimeError("No available AI providers found.")

    @classmethod
    async def generate_stream(cls, prompt: str, model: str = "default", **kwargs) -> AsyncGenerator[str, None]:
        try:
            provider, routed_model = ModelRouter.select_provider(prompt)
            if provider:
                final_model = routed_model if model == "default" else model
                async for chunk in provider.generate_stream(prompt, final_model, **kwargs):
                    yield chunk
                return
        except Exception as e:
            logger.error(f"Routing stream failed: {e}")

        if cls._legacy_default:
            async for chunk in cls._legacy_default.generate_stream(prompt, model, **kwargs):
                yield chunk
            return

        raise RuntimeError("No available AI providers found.")

    @classmethod
    async def is_backend_ready(cls) -> bool:
        """Check if any provider is ready"""
        providers = ProviderRegistry.get_all()
        for p in providers:
            if await p.check_availability():
                return True
                
        if cls._legacy_default:
            return await cls._legacy_default.check_availability()
            
        return False
