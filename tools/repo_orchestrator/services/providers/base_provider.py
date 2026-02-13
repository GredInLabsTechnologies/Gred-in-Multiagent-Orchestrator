from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional

class BaseProvider(ABC):
    """
    Abstract Base Class for AI Model Providers.
    """
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Type of provider (ollama, groq, openai, etc.)"""
        pass

    @property
    @abstractmethod
    def is_local(self) -> bool:
        """Whether the provider runs locally"""
        pass
    
    @abstractmethod
    async def generate(self, prompt: str, model: str, **kwargs) -> str:
        """Generate a complete response"""
        pass

    @abstractmethod
    async def generate_stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        """Stream the generation"""
        pass

    @abstractmethod
    async def check_availability(self) -> bool:
        """Check if the provider is reachable and healthy"""
        pass

    @abstractmethod
    async def list_models(self) -> List[str]:
        """List available models"""
        pass
