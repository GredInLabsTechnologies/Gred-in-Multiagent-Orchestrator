import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class LLMResponseCache:
    """Implement caching for LLM responses to reduce costs and latency."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_key(self, code: str, analysis_type: str) -> str:
        """Generate a stable SHA256 key from content and analysis type."""
        payload = f"{code}:{analysis_type}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, code: str, analysis_type: str) -> Optional[Dict]:
        """Retrieve a cached response if available."""
        key = self.get_cache_key(code, analysis_type)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None

    def set(self, code: str, analysis_type: str, result: Dict):
        """
        Cache a successful result.

        result expected format:
        {
            'response': str,
            'metadata': dict,
            'success': bool
        }
        """
        if not result.get("success", False):
            return

        key = self.get_cache_key(code, analysis_type)
        cache_file = self.cache_dir / f"{key}.json"

        cache_data = {
            "result": result.get("response"),
            "metadata": result.get("metadata", {}),
            "cached_at": datetime.now().isoformat(),
        }

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except IOError:
            # Silently fail if cannot write cache
            pass
