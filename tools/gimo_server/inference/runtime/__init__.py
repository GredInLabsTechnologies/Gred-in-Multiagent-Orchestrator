"""GIMO Inference Engine — Runtime Abstraction Layer.

Public API::

    from inference.runtime import OnnxAdapter, GgufAdapter, SessionPool, SessionHandle
    from inference.runtime import RuntimeAdapter, select_ep_chain, EP_PRIORITY
"""
from .base_adapter import EP_PRIORITY, RuntimeAdapter, SessionHandle, select_ep_chain
from .gguf_adapter import GgufAdapter
from .onnx_adapter import OnnxAdapter
from .session_pool import PoolMetrics, SessionPool

__all__ = [
    "RuntimeAdapter",
    "SessionHandle",
    "EP_PRIORITY",
    "select_ep_chain",
    "OnnxAdapter",
    "GgufAdapter",
    "SessionPool",
    "PoolMetrics",
]
