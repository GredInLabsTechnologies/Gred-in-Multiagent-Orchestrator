"""GIMO Inference Engine (GIE) — hardware-aware local inference subsystem.

Architecture:
    Agent Task -> GIMO Orchestrator -> Inference Layer -> Runtime (ONNX) -> EP -> CPU/GPU/NPU

The engine abstracts hardware heterogeneity behind a unified task-based API,
enabling automatic routing of semantic tasks (embedding, vision, reasoning,
code generation) to the optimal hardware backend.
"""

__version__ = "0.1.0"
