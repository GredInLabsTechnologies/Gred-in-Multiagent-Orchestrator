"""Model cache — disk-based store for compiled/optimised model artefacts.

Cache structure::

    ~/.gimo/models/
        <model_id>/
            <target>_<quant>/
                model.onnx          # compiled artefact
                metadata.json       # CompiledModelInfo serialised

Invalidation keys:
    - Source model file SHA-256 hash
    - Compiler version string (bumped on breaking changes)

LRU eviction based on last-access timestamp, respecting ``max_cache_gb``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from ..contracts import (
    CompiledModelInfo,
    ExecutionProviderType,
    HardwareTarget,
    ModelSpec,
    QuantizationType,
)

logger = logging.getLogger("gie.compiler.cache")

_COMPILER_VERSION = "1.0.0"   # bump when compiled format changes


class ModelCache:
    """Disk-backed cache for compiled model artefacts.

    Args:
        cache_dir:    Root directory; defaults to ``~/.gimo/models``.
        max_cache_gb: Soft cap.  LRU eviction runs when exceeded.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_cache_gb: float = 50.0,
    ) -> None:
        self._root = cache_dir or (Path.home() / ".gimo" / "models")
        self._max_bytes = int(max_cache_gb * 1024**3)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(
        self,
        model_id: str,
        target: HardwareTarget,
        quantization: QuantizationType,
    ) -> Optional[CompiledModelInfo]:
        """Return cached metadata if a valid compiled model exists, else None."""
        slot = self._slot(model_id, target, quantization)
        meta_path = slot / "metadata.json"
        compiled_path = slot / "model.onnx"

        if not meta_path.exists():
            return None

        try:
            with meta_path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt cache entry %s: %s", slot, exc)
            self._evict_slot(slot)
            return None

        # Validate compiler version.
        if data.get("_compiler_version") != _COMPILER_VERSION:
            logger.info("Cache entry %s outdated (compiler version mismatch)", slot)
            self._evict_slot(slot)
            return None

        # Check the compiled artefact still exists (path comes from metadata).
        compiled_path = Path(data["compiled_path"])
        if not compiled_path.exists():
            logger.warning("Cached artefact missing: %s; evicting entry", compiled_path)
            self._evict_slot(slot)
            return None

        # Update atime for LRU purposes.
        try:
            os.utime(meta_path)
        except OSError:
            pass

        return CompiledModelInfo(
            model_id=data["model_id"],
            compiled_path=compiled_path,
            target_device=HardwareTarget(data["target_device"]),
            execution_provider=ExecutionProviderType(data["execution_provider"]),
            quantization=QuantizationType(data["quantization"]),
            compiled_at=data.get("compiled_at", 0.0),
            compile_time_seconds=data.get("compile_time_seconds", 0.0),
            compiled_size_bytes=data.get("compiled_size_bytes", 0),
            checksum=data.get("checksum", ""),
        )

    def exists(
        self,
        model_id: str,
        target: HardwareTarget,
        quantization: QuantizationType,
    ) -> bool:
        return self.get(model_id, target, quantization) is not None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(self, info: CompiledModelInfo) -> None:
        """Store compiled model metadata in the cache."""
        slot = self._slot(info.model_id, info.target_device, info.quantization)
        slot.mkdir(parents=True, exist_ok=True)

        data = {
            "_compiler_version": _COMPILER_VERSION,
            "model_id": info.model_id,
            "compiled_path": str(info.compiled_path),
            "target_device": info.target_device.value,
            "execution_provider": info.execution_provider.value,
            "quantization": info.quantization.value,
            "compiled_at": info.compiled_at,
            "compile_time_seconds": info.compile_time_seconds,
            "compiled_size_bytes": info.compiled_size_bytes,
            "checksum": info.checksum,
        }
        meta_path = slot / "metadata.json"
        with meta_path.open("w") as f:
            json.dump(data, f, indent=2)

        logger.info("Cached compiled model: %s / %s", info.model_id, slot.name)
        self._maybe_evict()

    # ------------------------------------------------------------------
    # Eviction
    # ------------------------------------------------------------------

    def total_size_bytes(self) -> int:
        total = 0
        for path in self._root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    def evict_lru(self, target_bytes: int) -> None:
        """Evict LRU slots until total size ≤ target_bytes."""
        slots = sorted(self._all_slots(), key=lambda p: self._last_access(p))
        for slot in slots:
            if self.total_size_bytes() <= target_bytes:
                break
            self._evict_slot(slot)

    def _maybe_evict(self) -> None:
        if self.total_size_bytes() > self._max_bytes:
            target = int(self._max_bytes * 0.8)   # evict to 80% capacity
            logger.info("Cache over limit; running LRU eviction to %d bytes", target)
            self.evict_lru(target)

    def _evict_slot(self, slot: Path) -> None:
        import shutil
        try:
            shutil.rmtree(slot)
            logger.info("Evicted cache slot: %s", slot.name)
        except OSError as exc:
            logger.warning("Failed to evict %s: %s", slot, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _slot(
        self,
        model_id: str,
        target: HardwareTarget,
        quantization: QuantizationType,
    ) -> Path:
        """Return the directory path for a given (model, target, quant) key."""
        key = f"{target.value}_{quantization.value}"
        return self._root / model_id / key

    def _all_slots(self) -> Iterator[Path]:
        for model_dir in self._root.iterdir():
            if model_dir.is_dir():
                for slot in model_dir.iterdir():
                    if slot.is_dir():
                        yield slot

    @staticmethod
    def _last_access(slot: Path) -> float:
        meta = slot / "metadata.json"
        try:
            return meta.stat().st_atime
        except OSError:
            return 0.0


# ---------------------------------------------------------------------------
# Source model checksum
# ---------------------------------------------------------------------------

def compute_checksum(path: Path, chunk_size: int = 1 << 20) -> str:
    """Return SHA-256 hex digest of *path* (for cache invalidation)."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()
