"""NPU backend configuration and capability reporting.

Handles AMD XDNA (VitisAI EP) and Intel Core Ultra (OpenVINO EP) NPUs.
NPUs are best suited for small-to-medium models with INT8 quantization.
They are particularly effective for embedding, classification, and attention
heads in hybrid sharding scenarios.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..contracts import DeviceCapability, ExecutionProviderType, HardwareTarget

logger = logging.getLogger("gie.hardware.npu")

# ---------------------------------------------------------------------------
# NPU model size constraints (conservative)
# ---------------------------------------------------------------------------
# NPU-only execution (quantized INT8):
NPU_ONLY_MAX_PARAMS_B = 3.0      # up to 3B params runs fully on NPU
# NPU + CPU hybrid:
NPU_HYBRID_MAX_PARAMS_B = 13.0   # up to 13B params with CPU overflow


@dataclass
class NpuConfig:
    """Recommended NPU inference configuration."""
    execution_provider: ExecutionProviderType
    provider_options: Dict[str, Any]
    quantization_required: str          # "int8" or "int4"
    max_model_params_b: float           # solo NPU limit
    max_hybrid_params_b: float          # NPU+CPU hybrid limit
    supports_attention_offload: bool    # embed + attention on NPU
    concurrent_sessions: int            # NPU pipelines are sequential → 1
    estimated_tps_7b_int8: float        # rough tok/sec for 7B INT8 hybrid


def get_npu_config(device: DeviceCapability) -> Optional[NpuConfig]:
    """Return NPU configuration or None if no NPU is present."""
    if device.device_type != HardwareTarget.NPU:
        return None

    providers = device.execution_providers
    name_lower = device.device_name.lower()

    # --------------- AMD XDNA (VitisAI) ---------------
    if ExecutionProviderType.VITIS_AI in providers or "xdna" in name_lower or "amd" in name_lower:
        ep = ExecutionProviderType.VITIS_AI
        opts = _vitis_ai_options(device)
        quant = "int4" if device.supports_int4 else "int8"
        # XDNA2 (Strix Halo 50 TOPS) can handle larger models.
        solo_limit = 5.0 if device.compute_tops >= 50 else NPU_ONLY_MAX_PARAMS_B
        hybrid_limit = 20.0 if device.compute_tops >= 50 else NPU_HYBRID_MAX_PARAMS_B
        # tok/sec estimate: 16 TOPS @ INT8 for 7B hybrid = rough ~5 tok/s NPU portion
        est_tps = min(20.0, device.compute_tops / 3.0)

        return NpuConfig(
            execution_provider=ep,
            provider_options=opts,
            quantization_required=quant,
            max_model_params_b=solo_limit,
            max_hybrid_params_b=hybrid_limit,
            supports_attention_offload=True,
            concurrent_sessions=1,
            estimated_tps_7b_int8=round(est_tps, 1),
        )

    # --------------- Intel Core Ultra (OpenVINO) ---------------
    if ExecutionProviderType.OPENVINO in providers or "intel" in name_lower:
        ep = ExecutionProviderType.OPENVINO
        opts = _openvino_npu_options()
        tops = device.compute_tops or 11.0
        solo_limit = 3.0 if tops < 30 else 7.0
        hybrid_limit = 7.0 if tops < 30 else 13.0
        est_tps = tops / 4.0

        return NpuConfig(
            execution_provider=ep,
            provider_options=opts,
            quantization_required="int8",
            max_model_params_b=solo_limit,
            max_hybrid_params_b=hybrid_limit,
            supports_attention_offload=True,
            concurrent_sessions=1,
            estimated_tps_7b_int8=round(est_tps, 1),
        )

    # Unknown NPU vendor — report basic config.
    return NpuConfig(
        execution_provider=ExecutionProviderType.CPU,
        provider_options={},
        quantization_required="int8",
        max_model_params_b=NPU_ONLY_MAX_PARAMS_B,
        max_hybrid_params_b=NPU_HYBRID_MAX_PARAMS_B,
        supports_attention_offload=False,
        concurrent_sessions=1,
        estimated_tps_7b_int8=2.0,
    )


def npu_can_handle(
    device: DeviceCapability,
    param_billions: float,
    *,
    hybrid: bool = False,
) -> bool:
    """Check whether the NPU can handle a model of the given size."""
    if device.device_type != HardwareTarget.NPU:
        return False
    config = get_npu_config(device)
    if config is None:
        return False
    limit = config.max_hybrid_params_b if hybrid else config.max_model_params_b
    return param_billions <= limit


def npu_layers_for_embedding_attention(
    total_layers: int,
    device: DeviceCapability,
) -> int:
    """How many transformer layers (embedding + attention) to place on NPU.

    Conservative: place only the first 25% of layers on NPU to avoid
    exceeding NPU memory (NPU memory is shared with system RAM on APUs).
    """
    config = get_npu_config(device)
    if config is None or not config.supports_attention_offload:
        return 0
    # NPU handles embedding (layer 0) + attention heads.
    # Rough heuristic: 25% of layers for embedding/attention.
    return max(1, total_layers // 4)


# ---------------------------------------------------------------------------
# Provider option builders
# ---------------------------------------------------------------------------

def _vitis_ai_options(device: DeviceCapability) -> Dict[str, Any]:
    """VitisAI EP options for AMD XDNA NPU."""
    opts: Dict[str, Any] = {}
    # config_file points to the Vitis AI quantization config.
    # In production this is populated from the GIMO model cache.
    # If not set, VitisAI falls back to runtime quantization.
    tops = device.compute_tops
    if tops >= 50:
        opts["target"] = "XDNA2"
    else:
        opts["target"] = "XDNA"
    opts["num_of_dpu_runners"] = 1
    return opts


def _openvino_npu_options() -> Dict[str, Any]:
    """OpenVINO EP options targeting the Intel NPU device."""
    return {
        "device_type": "NPU",
        "enable_opencl_throttling": "true",
        "enable_dynamic_shapes": "false",
    }
