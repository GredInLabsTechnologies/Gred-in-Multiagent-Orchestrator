"""Model Catalog Service — serves GGUF models to mesh devices.

Scans OPS_DATA_DIR/mesh/models/ for .gguf files and provides metadata
for the device setup wizard (model selection + download).
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from ...config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.mesh.model_catalog")

_MODELS_DIR = Path(OPS_DATA_DIR) / "mesh" / "models"

# Pattern: qwen2.5_3b_q4_k_m.gguf → name=qwen2.5, params=3b, quant=q4_k_m
_GGUF_PATTERN = re.compile(
    r"^(?P<name>[a-zA-Z0-9._-]+?)(?:[-_](?P<params>\d+\.?\d*[bBmM]))?(?:[-_](?P<quant>[qQ]\d[a-zA-Z0-9_]*))?\\.gguf$"
)


class ModelInfo(BaseModel):
    """Metadata for a GGUF model available for download."""
    model_id: str
    filename: str
    name: str
    params: str = ""
    quantization: str = ""
    size_bytes: int = 0
    sha256: str = ""


class ModelCatalogService:
    """Scans and caches model metadata from the models directory."""

    def __init__(self) -> None:
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, ModelInfo] = {}

    def list_models(self) -> List[ModelInfo]:
        """List all available GGUF models with metadata."""
        result: List[ModelInfo] = []
        for f in sorted(_MODELS_DIR.glob("*.gguf")):
            if not f.is_file():
                continue
            info = self._get_model_info(f)
            if info:
                result.append(info)
        return result

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """Get metadata for a specific model."""
        for model in self.list_models():
            if model.model_id == model_id:
                return model
        return None

    def get_model_path(self, model_id: str) -> Optional[Path]:
        """Get the file path for a model, or None if not found."""
        model = self.get_model(model_id)
        if model is None:
            return None
        path = _MODELS_DIR / model.filename
        return path if path.exists() else None

    def _get_model_info(self, path: Path) -> Optional[ModelInfo]:
        """Parse model metadata from filename + file stats."""
        filename = path.name

        # Use cache if size hasn't changed
        if filename in self._cache:
            cached = self._cache[filename]
            if cached.size_bytes == path.stat().st_size:
                return cached

        # Parse filename
        match = _GGUF_PATTERN.match(filename)
        if match:
            name = match.group("name") or filename.replace(".gguf", "")
            params = match.group("params") or ""
            quant = match.group("quant") or ""
        else:
            # Fallback: use filename without extension
            name = filename.replace(".gguf", "")
            params = ""
            quant = ""

        # Generate stable model_id from filename
        model_id = filename.replace(".gguf", "").lower().replace(" ", "-")

        # SHA-256 (compute once, cache)
        sha = self._compute_sha256(path)

        info = ModelInfo(
            model_id=model_id,
            filename=filename,
            name=name,
            params=params,
            quantization=quant,
            size_bytes=path.stat().st_size,
            sha256=sha,
        )
        self._cache[filename] = info
        return info

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        """Compute SHA-256 of a file in chunks (handles multi-GB files)."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            logger.warning("Failed to compute SHA-256 for %s: %s", path.name, e)
            return ""
