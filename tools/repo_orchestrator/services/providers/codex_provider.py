from typing import AsyncGenerator, List, Dict, Any
import httpx
import json
import logging
import os
from .base_provider import BaseProvider

logger = logging.getLogger("orchestrator.providers.codex")

class CodexProvider(BaseProvider):
    """
    Provider for OpenAI/Codex (Subscription based).
    Used for complex "Architect" tasks.
    """
    
    @property
    def provider_type(self) -> str:
        return "codex"

    @property
    def is_local(self) -> bool:
        return False

    def _get_api_key(self) -> str:
        return self.config.get("api_key") or os.environ.get("OPENAI_API_KEY")

    def _get_base_url(self) -> str:
        return self.config.get("base_url", "https://api.openai.com/v1")

    async def generate(self, prompt: str, model: str, **kwargs) -> str:
        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("OpenAI API Key not found")

        url = f"{self._get_base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        messages = [{"role": "user", "content": prompt}]
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": False
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Codex generation failed: {e}")
            raise

    async def generate_stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("OpenAI API Key not found")

        url = f"{self._get_base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        messages = [{"role": "user", "content": prompt}]
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True
        }

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, headers=headers, json=payload, timeout=60.0) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            line = line[6:]
                            if line == "[DONE]":
                                break
                            try:
                                data = json.loads(line)
                                delta = data["choices"][0]["delta"]
                                if "content" in delta:
                                    yield delta["content"]
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Codex streaming failed: {e}")
            raise

    async def check_availability(self) -> bool:
        api_key = self._get_api_key()
        if not api_key:
            return False
            
        url = f"{self._get_base_url()}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                return resp.status_code == 200
        except:
            return False

    async def list_models(self) -> List[str]:
        api_key = self._get_api_key()
        if not api_key:
            return []
            
        url = f"{self._get_base_url()}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["id"] for m in data.get("data", [])]
                return []
        except Exception as e:
            logger.error(f"Failed to list Codex models: {e}")
            return []
