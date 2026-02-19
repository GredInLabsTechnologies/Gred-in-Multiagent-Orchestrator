from __future__ import annotations

import shutil
from typing import Dict, Optional

from ..adapters.base import AgentAdapter
from ..adapters.codex import CodexAdapter
from ..adapters.gemini import GeminiAdapter
from ..adapters.openai_compatible import OpenAICompatibleAdapter

class AdapterRegistry:
    _adapters: Dict[str, AgentAdapter] = {}
    _availability: Dict[str, bool] = {}

    @classmethod
    def register(cls, name: str, adapter: AgentAdapter):
        cls._adapters[name] = adapter

    @classmethod
    def get(cls, name: str) -> Optional[AgentAdapter]:
        return cls._adapters.get(name)

    @classmethod
    def list_registered(cls) -> Dict[str, AgentAdapter]:
        return dict(cls._adapters)

    @classmethod
    def is_available(cls, name: str) -> bool:
        return bool(cls._availability.get(name, True))

    @classmethod
    def reset(cls) -> None:
        cls._adapters = {}
        cls._availability = {}

    @classmethod
    def _binary_available(cls, binary_name: str) -> bool:
        return shutil.which(binary_name) is not None

    @classmethod
    def initialize_defaults(cls):
        cls.reset()

        # Always-available local adapter
        cls.register("local", OpenAICompatibleAdapter(model_name="qwen-2.5-7b-instruct"))
        cls._availability["local"] = True

        # Optional CLI adapters (health-check via PATH lookup)
        codex_available = cls._binary_available("codex")
        cls._availability["codex"] = codex_available
        if codex_available:
            cls.register("codex", CodexAdapter(binary_path="codex"))

        gemini_available = cls._binary_available("gemini")
        cls._availability["gemini"] = gemini_available
        if gemini_available:
            cls.register("gemini", GeminiAdapter(binary_path="gemini"))
