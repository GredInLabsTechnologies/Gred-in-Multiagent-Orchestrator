"""Core data contracts for the GIMO Inference Engine."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HardwareTarget(str, enum.Enum):
    CPU = "cpu"
    GPU = "gpu"
    NPU = "npu"
    AUTO = "auto"  # let the scheduler decide


class QuantizationType(str, enum.Enum):
    NONE = "none"
    INT8 = "int8"
    INT4 = "int4"
    BF16 = "bf16"
    FP16 = "fp16"
    GPTQ = "gptq"
    AWQ = "awq"


class TaskSemantic(str, enum.Enum):
    """Semantic task types that map to hardware affinity."""
    EMBEDDING = "embedding"
    VISION = "vision"
    SPEECH = "speech"
    REASONING = "reasoning"
    CODE_GENERATION = "code_generation"
    RERANKING = "reranking"
    CLASSIFICATION = "classification"
    DIFFUSION = "diffusion"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    GENERAL = "general"


class ModelFormat(str, enum.Enum):
    ONNX = "onnx"
    GGUF = "gguf"
    SAFETENSORS = "safetensors"
    PYTORCH = "pytorch"
    OPENVINO = "openvino"
    COREML = "coreml"


class ExecutionProviderType(str, enum.Enum):
    CPU = "CPUExecutionProvider"
    CUDA = "CUDAExecutionProvider"
    TENSORRT = "TensorrtExecutionProvider"
    DIRECTML = "DmlExecutionProvider"
    OPENVINO = "OpenVINOExecutionProvider"
    VITIS_AI = "VitisAIExecutionProvider"
    QNN = "QNNExecutionProvider"
    COREML = "CoreMLExecutionProvider"
    ROCM = "ROCMExecutionProvider"


class ShardStrategy(str, enum.Enum):
    """How to split a model that exceeds single-device memory."""
    NONE = "none"
    LAYER_SPLIT = "layer_split"        # split transformer layers across devices
    TENSOR_PARALLEL = "tensor_parallel"  # split individual tensors
    OFFLOAD_CPU = "offload_cpu"          # keep overflow layers in RAM
    OFFLOAD_DISK = "offload_disk"        # mmap from disk (slowest)
    HYBRID = "hybrid"                    # GPU + CPU + disk cascade


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    """Describes a model available for local inference."""
    model_id: str
    path: Path
    format: ModelFormat
    size_bytes: int = 0
    param_count_b: float = 0.0          # billions of parameters
    quantization: QuantizationType = QuantizationType.NONE
    opset_version: int = 0              # ONNX opset
    supported_tasks: List[TaskSemantic] = field(default_factory=list)
    max_sequence_length: int = 4096
    vocab_size: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceCapability:
    """Hardware capability snapshot for a single compute device."""
    device_type: HardwareTarget
    device_name: str
    total_memory_gb: float
    free_memory_gb: float
    compute_tops: float = 0.0           # TOPS for NPU, TFLOPS for GPU
    memory_bandwidth_gbps: float = 0.0  # crucial for LLM inference
    supports_int8: bool = True
    supports_bf16: bool = False
    supports_int4: bool = False
    execution_providers: List[ExecutionProviderType] = field(default_factory=list)
    is_unified_memory: bool = False     # APU/SoC shared memory
    temperature_celsius: float = 0.0
    utilization_percent: float = 0.0


@dataclass
class InferenceRequest:
    """A request to run inference on a model."""
    request_id: str
    model_id: str
    task: TaskSemantic
    inputs: Dict[str, Any]
    target_hardware: HardwareTarget = HardwareTarget.AUTO
    max_tokens: int = 2048
    temperature: float = 0.7
    priority: int = 5                   # 1=highest, 10=lowest
    timeout_seconds: float = 120.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceResult:
    """Result from a completed inference request."""
    request_id: str
    model_id: str
    outputs: Dict[str, Any]
    hardware_used: HardwareTarget
    device_name: str
    execution_provider: str
    latency_ms: float
    tokens_generated: int = 0
    tokens_per_second: float = 0.0
    memory_peak_mb: float = 0.0
    shard_strategy_used: ShardStrategy = ShardStrategy.NONE
    error: Optional[str] = None


@dataclass
class MemoryBudget:
    """Calculated memory budget for model loading."""
    gpu_available_gb: float
    cpu_available_gb: float
    npu_available_gb: float
    disk_cache_gb: float
    total_usable_gb: float              # sum of all above
    reserved_system_gb: float = 2.0     # always keep 2GB free for OS
    model_requires_gb: float = 0.0
    fits_single_device: bool = True
    recommended_shard: ShardStrategy = ShardStrategy.NONE
    shard_plan: Dict[str, float] = field(default_factory=dict)  # device -> GB


@dataclass
class CompiledModelInfo:
    """Metadata for a compiled/cached model."""
    model_id: str
    compiled_path: Path
    target_device: HardwareTarget
    execution_provider: ExecutionProviderType
    quantization: QuantizationType
    compiled_at: float = field(default_factory=time.time)
    compile_time_seconds: float = 0.0
    compiled_size_bytes: int = 0
    checksum: str = ""
