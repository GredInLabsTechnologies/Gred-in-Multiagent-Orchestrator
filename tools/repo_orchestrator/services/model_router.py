import logging
import random
from typing import Optional, Tuple
from .provider_registry import ProviderRegistry
from .node_manager import NodeManager
from .providers.base_provider import BaseProvider

logger = logging.getLogger("orchestrator.model_router")

class ModelRouter:
    """
    Intelligent routing for tasks.
    Decides between Local (NPU) and Cloud (Groq/Codex).
    """
    
    KEYWORDS_ARCHITECT = ["refactor", "design", "architecture", "plan", "complex", "debug", "schema"]
    KEYWORDS_CODE_MONKEY = ["test", "json", "interface", "regex", "script", "simple", "validate"]

    @classmethod
    def classify_task(cls, task_description: str) -> str:
        """Returns 'architect' or 'code_monkey'"""
        desc_lower = task_description.lower()
        
        # Check Architect keywords
        for kw in cls.KEYWORDS_ARCHITECT:
            if kw in desc_lower:
                return "architect"
                
        # Default to code_monkey if simple enough
        return "code_monkey"

    @classmethod
    def select_provider(cls, task: str, preferred_type: Optional[str] = None) -> Tuple[Optional[BaseProvider], str]:
        """
        Returns (Provider, ModelName) based on strategy.
        """
        classification = cls.classify_task(task)
        providers = ProviderRegistry.get_all()
        
        if not providers:
            return None, ""

        # 1. User Preference Override
        if preferred_type:
            matches = [p for p in providers if p.provider_type == preferred_type]
            if matches:
                # Just pick first matching provider for now
                return matches[0], "default" # Model selection to be refined

        # 2. Architect Tasks -> Cloud First
        if classification == "architect":
            cloud_providers = [p for p in providers if not p.is_local]
            if cloud_providers:
                # Prioritize Groq (Free) -> Codex (Paid) -> OpenRouter
                # Simple logic: precise filtering
                groq = next((p for p in cloud_providers if p.provider_type == "groq"), None)
                if groq: return groq, "llama3-70b-8192"
                
                codex = next((p for p in cloud_providers if p.provider_type == "codex"), None)
                if codex: return codex, "gpt-4o"
                
                return cloud_providers[0], "default"

        # 3. Code Monkey Tasks -> Local First
        local_providers = [p for p in providers if p.is_local]
        if local_providers:
            # Check availability/load? (NodeManager handle concurrency blocks, here we just pick provider)
            # Default to Ollama
            ollama = next((p for p in local_providers if p.provider_type == "ollama"), None)
            if ollama: return ollama, "qwen2.5-coder:1.5b"
            return local_providers[0], "default"

        # 4. Fallback (If no local provider for monkey task, use cloud)
        if providers:
            return providers[0], "default"
            
        return None, ""
