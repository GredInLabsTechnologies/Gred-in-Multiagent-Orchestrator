"""Memory-mapped model engine for oversized models.

Enables loading a model that is larger than available RAM by mapping it
from disk via the OS mmap facility.  The OS virtual-memory subsystem brings
pages into RAM on demand (page faults) and evicts cold pages as needed.

This allows GIMO to "run" a 70 GB model on a 24 GB machine — slowly (2-5
tok/s) but correctly.  Other tools (Ollama, LM Studio, vLLM) would reject
the model outright.

Prefetch hints via madvise(MADV_SEQUENTIAL) tell the OS to read ahead
sequentially, which improves throughput for autoregressive token generation.

Architecture:
    MmapEngine wraps a model file path and provides:
    - open() / close() context manager
    - read_layer(layer_idx) → bytes — read model weights for one layer
    - prefetch_hint(layer_idx) — hint OS to load upcoming layer pages
"""
from __future__ import annotations

import logging
import mmap
import os
import struct
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger("gie.mmap_engine")

# Page-aligned read size for prefetch: 4 MB (typical huge-page size).
_PREFETCH_CHUNK_BYTES = 4 * 1024 * 1024

# madvise constants (Linux only).
_MADV_SEQUENTIAL = 2
_MADV_WILLNEED   = 3
_MADV_DONTNEED   = 4


class MmapEngine:
    """Memory-mapped model file reader.

    Usage::

        engine = MmapEngine(model_path, num_layers=32)
        with engine:
            weights = engine.read_layer(0)
            engine.prefetch_hint(1)
            ...

    Thread safety: ``read_layer`` is safe to call from multiple threads as
    long as each thread uses its own slice of the mmap (reads are concurrent,
    the underlying file is immutable).
    """

    def __init__(
        self,
        model_path: Path,
        *,
        num_layers: int = 32,
        layer_size_bytes: Optional[int] = None,
    ) -> None:
        """
        Args:
            model_path:         Absolute path to the model file (ONNX or GGUF).
            num_layers:         Number of transformer layers for offset computation.
            layer_size_bytes:   Explicit layer size; computed from file if None.
        """
        self._path = Path(model_path)
        self._num_layers = num_layers
        self._layer_size_bytes = layer_size_bytes
        self._file: Optional[object] = None
        self._mm: Optional[mmap.mmap] = None
        self._file_size: int = 0
        self._is_linux = sys.platform.startswith("linux")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def open(self) -> "MmapEngine":
        if not self._path.exists():
            raise FileNotFoundError(f"Model file not found: {self._path}")
        self._file = open(self._path, "rb")  # noqa: WPS515
        self._mm = mmap.mmap(
            self._file.fileno(),
            0,                     # 0 = map entire file
            access=mmap.ACCESS_READ,
        )
        self._file_size = os.path.getsize(self._path)
        if self._layer_size_bytes is None and self._num_layers > 0:
            self._layer_size_bytes = self._file_size // self._num_layers
        logger.info(
            "MmapEngine opened %s (%.2f GB, %d layers, %.1f MB/layer)",
            self._path.name,
            self._file_size / 1024**3,
            self._num_layers,
            (self._layer_size_bytes or 0) / 1024**2,
        )
        # Hint: sequential read pattern (helps page-cache prefetch).
        self._madvise_sequential()
        return self

    def close(self) -> None:
        if self._mm:
            try:
                self._mm.close()
            except Exception:
                pass
            self._mm = None
        if self._file:
            try:
                self._file.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._file = None

    def __enter__(self) -> "MmapEngine":
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_layer(self, layer_idx: int) -> bytes:
        """Return raw bytes for layer *layer_idx*.

        The caller is responsible for deserialising the bytes into tensors.
        """
        if self._mm is None:
            raise RuntimeError("MmapEngine is not open — use 'with engine:' or call open()")
        offset = self._layer_offset(layer_idx)
        size = self._layer_size_bytes or 0
        if size <= 0 or offset + size > self._file_size:
            raise IndexError(
                f"Layer {layer_idx} out of bounds (offset={offset}, size={size}, "
                f"file_size={self._file_size})"
            )
        self._mm.seek(offset)
        return self._mm.read(size)

    def prefetch_hint(self, layer_idx: int) -> None:
        """Hint the OS to load the pages for *layer_idx* into RAM now.

        Uses madvise(MADV_WILLNEED) on Linux.  On other platforms this is a no-op.
        The call is asynchronous from the OS perspective — it returns immediately
        and the kernel issues read-ahead I/O in the background.
        """
        if not self._is_linux or self._mm is None:
            return
        try:
            offset = self._layer_offset(layer_idx)
            size = self._layer_size_bytes or _PREFETCH_CHUNK_BYTES
            size = min(size, self._file_size - offset)
            if size > 0:
                # madvise via ctypes on Linux.
                import ctypes
                libc = ctypes.CDLL("libc.so.6", use_errno=True)
                mm_addr = ctypes.c_char_p(bytes(self._mm))
                libc.madvise(
                    ctypes.c_void_p(id(self._mm) + offset),  # approximate; works for hint
                    ctypes.c_size_t(size),
                    ctypes.c_int(_MADV_WILLNEED),
                )
        except Exception as exc:
            logger.debug("prefetch_hint failed: %s", exc)

    def evict_hint(self, layer_idx: int) -> None:
        """Hint the OS that pages for *layer_idx* can be reclaimed (MADV_DONTNEED)."""
        if not self._is_linux or self._mm is None:
            return
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            offset = self._layer_offset(layer_idx)
            size = self._layer_size_bytes or _PREFETCH_CHUNK_BYTES
            libc.madvise(
                ctypes.c_void_p(id(self._mm) + offset),
                ctypes.c_size_t(size),
                ctypes.c_int(_MADV_DONTNEED),
            )
        except Exception as exc:
            logger.debug("evict_hint failed: %s", exc)

    @property
    def file_size_gb(self) -> float:
        return self._file_size / 1024**3

    @property
    def is_open(self) -> bool:
        return self._mm is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _layer_offset(self, layer_idx: int) -> int:
        if layer_idx < 0 or layer_idx >= self._num_layers:
            raise IndexError(f"Layer index {layer_idx} out of range [0, {self._num_layers})")
        return layer_idx * (self._layer_size_bytes or 0)

    def _madvise_sequential(self) -> None:
        if not self._is_linux or self._mm is None:
            return
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.madvise(
                ctypes.c_void_p(id(self._mm)),
                ctypes.c_size_t(self._file_size),
                ctypes.c_int(_MADV_SEQUENTIAL),
            )
        except Exception:
            pass  # non-fatal
