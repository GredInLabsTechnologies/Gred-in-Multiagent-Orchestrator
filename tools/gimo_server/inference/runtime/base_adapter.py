"""Protocol definition for all runtime adapters in the GIMO Inference Engine.

Every concrete adapter (ONNX, GGUF, …) must satisfy this Protocol so the
rest of the engine can work with any backend transparently.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Protocol, runtime_checkable

from ..contracts import ExecutionProviderType, HardwareTarget, ModelSpec


# ---------------------------------------------------------------------------
# Session handle — lightweight reference to a loaded model session
# ---------------------------------------------------------------------------

@dataclass
class SessionHandle:
    """Opaque reference to an active runtime session.

    Adapters may subclass this to attach backend-specific state, but callers
    must not rely on adapter-specific fields — use the public attributes only.
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    model_id: str = ""
    model_path: Path = field(default_factory=Path)
    hardware_target: HardwareTarget = HardwareTarget.CPU
    execution_provider: ExecutionProviderType = ExecutionProviderType.CPU
    # Memory occupied by this session, as reported by the adapter.
    memory_mb: float = 0.0
    # Wall-clock timestamp when the session was last used.
    last_used: float = 0.0
    # Arbitrary adapter-private state (e.g. the real ort.InferenceSession).
    _backend: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# RuntimeAdapter Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class RuntimeAdapter(Protocol):
    """Structural protocol that every runtime adapter must implement.

    Adapters are *not* required to inherit from a base class; duck-typing via
    ``isinstance(obj, RuntimeAdapter)`` works because of ``@runtime_checkable``.
    """

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def load_model(
        self,
        spec: ModelSpec,
        device: HardwareTarget,
    ) -> SessionHandle:
        """Load *spec* on *device* and return an opaque session handle.

        The adapter is responsible for:
        - Selecting the best ExecutionProvider chain for *device*.
        - Setting session options (thread count, memory arena, IO binding).
        - Reporting approximate memory usage in the returned handle.
        """
        ...

    async def run(
        self,
        session: SessionHandle,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a forward pass and return the output dict.

        ``inputs`` keys and value types depend on the model; adapters must
        NOT modify the caller-supplied dict in place.
        """
        ...

    async def unload(self, session: SessionHandle) -> None:
        """Release all resources held by *session*.

        After this call the handle is invalid and must not be re-used.
        """
        ...

    # ------------------------------------------------------------------
    # Capability introspection
    # ------------------------------------------------------------------

    def get_available_providers(self) -> List[ExecutionProviderType]:
        """Return the EPs that are actually available in this environment."""
        ...

    def get_provider_options(
        self,
        ep: ExecutionProviderType,
    ) -> Dict[str, Any]:
        """Return EP-specific options dict (passed to the backend verbatim).

        Returns an empty dict for unknown EPs — callers must not raise.
        """
        ...

    def supports_format(self, fmt: str) -> bool:
        """Return True if this adapter can load models of the given format.

        *fmt* is a :class:`~inference.contracts.ModelFormat` value string.
        """
        ...


# ---------------------------------------------------------------------------
# Helper: EP priority chains per hardware target
# ---------------------------------------------------------------------------

#: For each HardwareTarget, ordered list of preferred EPs (first = highest prio).
EP_PRIORITY: Dict[HardwareTarget, List[ExecutionProviderType]] = {
    HardwareTarget.NPU: [
        ExecutionProviderType.VITIS_AI,
        ExecutionProviderType.OPENVINO,
        ExecutionProviderType.QNN,
        ExecutionProviderType.DIRECTML,
        ExecutionProviderType.CPU,
    ],
    HardwareTarget.GPU: [
        ExecutionProviderType.CUDA,
        ExecutionProviderType.TENSORRT,
        ExecutionProviderType.ROCM,
        ExecutionProviderType.DIRECTML,
        ExecutionProviderType.CPU,
    ],
    HardwareTarget.CPU: [
        ExecutionProviderType.CPU,
    ],
    HardwareTarget.AUTO: [
        ExecutionProviderType.CUDA,
        ExecutionProviderType.VITIS_AI,
        ExecutionProviderType.ROCM,
        ExecutionProviderType.DIRECTML,
        ExecutionProviderType.OPENVINO,
        ExecutionProviderType.CPU,
    ],
}


def select_ep_chain(
    target: HardwareTarget,
    available: List[ExecutionProviderType],
) -> List[ExecutionProviderType]:
    """Return the subset of *available* EPs in priority order for *target*.

    Always ends with ``CPUExecutionProvider`` as an ultimate fallback.
    """
    priority = EP_PRIORITY.get(target, EP_PRIORITY[HardwareTarget.AUTO])
    chain = [ep for ep in priority if ep in available]
    if ExecutionProviderType.CPU not in chain:
        chain.append(ExecutionProviderType.CPU)
    return chain
