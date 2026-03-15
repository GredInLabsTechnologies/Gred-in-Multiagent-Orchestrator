"""Inference Engine REST API.

Exposes the GIMO Inference Engine (GIE) over HTTP so external tools and the
frontend can query engine status, manage loaded models, and run local inference.

Endpoints:
    GET  /api/ops/inference/status      — engine status + session pool
    GET  /api/ops/inference/devices     — detected devices with capabilities
    GET  /api/ops/inference/models      — currently loaded model sessions
    POST /api/ops/inference/load        — preload a model into the pool
    POST /api/ops/inference/unload      — evict a model from the pool
    POST /api/ops/inference/run         — execute an inference request
    GET  /api/ops/inference/metrics     — telemetry counters

All endpoints require operator-level auth (same as other ops routers).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from .common import _actor_label, _require_role

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RegisterModelRequest(BaseModel):
    model_id: str
    path: str
    format: str = "onnx"        # ModelFormat value
    size_bytes: int = 0
    param_count_b: float = 0.0
    quantization: str = "none"  # QuantizationType value
    supported_tasks: List[str] = Field(default_factory=list)


class LoadModelRequest(BaseModel):
    model_id: str
    target: str = "auto"  # "cpu", "gpu", "npu", "auto"


class UnloadModelRequest(BaseModel):
    model_id: str


class RunInferenceRequest(BaseModel):
    model_id: str
    task: str = "general"           # TaskSemantic value
    inputs: Dict[str, Any] = Field(default_factory=dict)
    target_hardware: str = "auto"
    max_tokens: int = 2048
    temperature: float = 0.7
    priority: int = 5
    timeout_seconds: float = 120.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_engine():
    from tools.gimo_server.inference.engine_service import InferenceEngineService
    return InferenceEngineService.get_instance()


def _parse_target(target_str: str):
    from tools.gimo_server.inference.contracts import HardwareTarget
    try:
        return HardwareTarget(target_str.lower())
    except ValueError:
        return HardwareTarget.AUTO


def _parse_task(task_str: str):
    from tools.gimo_server.inference.contracts import TaskSemantic
    try:
        return TaskSemantic(task_str.lower())
    except ValueError:
        return TaskSemantic.GENERAL


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/inference/register")
async def register_model(
    body: RegisterModelRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Register a model spec so it can be loaded and used for inference.

    This must be called (e.g. at startup) before any /inference/load or
    /inference/run request for this model_id will succeed.
    """
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/register", body.model_id, operation="WRITE", actor=_actor_label(auth))

    from pathlib import Path as _Path
    from tools.gimo_server.inference.contracts import (
        ModelFormat, ModelSpec, QuantizationType, TaskSemantic,
    )

    try:
        fmt = ModelFormat(body.format.lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown model format: {body.format}")

    try:
        quant = QuantizationType(body.quantization.lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown quantization: {body.quantization}")

    tasks = []
    for t in body.supported_tasks:
        try:
            tasks.append(TaskSemantic(t.lower()))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown task semantic: {t}")

    spec = ModelSpec(
        model_id=body.model_id,
        path=_Path(body.path),
        format=fmt,
        size_bytes=body.size_bytes,
        param_count_b=body.param_count_b,
        quantization=quant,
        supported_tasks=tasks,
    )
    _get_engine().register_model(spec)
    return {"registered": True, "model_id": body.model_id, "format": fmt.value}


@router.get("/inference/status")
async def get_inference_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Return overall engine status including device list and session pool."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/status", "status", operation="READ", actor=_actor_label(auth))
    engine = _get_engine()
    if not engine._initialized:
        return {"initialized": False, "message": "Engine not yet initialized"}
    return engine.get_status()


@router.get("/inference/devices")
async def get_inference_devices(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> List[Dict[str, Any]]:
    """Return list of detected compute devices with capabilities."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/devices", "devices", operation="READ", actor=_actor_label(auth))
    engine = _get_engine()
    return [
        {
            "type": d.device_type.value,
            "name": d.device_name,
            "total_memory_gb": d.total_memory_gb,
            "free_memory_gb": d.free_memory_gb,
            "compute_tops": d.compute_tops,
            "memory_bandwidth_gbps": d.memory_bandwidth_gbps,
            "supports_int8": d.supports_int8,
            "supports_bf16": d.supports_bf16,
            "supports_int4": d.supports_int4,
            "is_unified_memory": d.is_unified_memory,
            "temperature_celsius": d.temperature_celsius,
            "utilization_percent": d.utilization_percent,
            "execution_providers": [ep.value for ep in d.execution_providers],
        }
        for d in engine.get_device_status()
    ]


@router.get("/inference/models")
async def get_loaded_models(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> List[Dict[str, Any]]:
    """Return currently loaded model sessions in the pool."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/models", "models", operation="READ", actor=_actor_label(auth))
    return _get_engine().get_loaded_models()


@router.post("/inference/load")
async def load_model(
    body: LoadModelRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Preload a model into the session pool."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/load", body.model_id, operation="WRITE", actor=_actor_label(auth))
    engine = _get_engine()
    if not engine._initialized:
        await engine.initialize()
    target = _parse_target(body.target)
    success = await engine.load_model(body.model_id, target)
    if not success:
        raise HTTPException(status_code=404, detail=f"Model '{body.model_id}' not found or failed to load")
    return {"loaded": True, "model_id": body.model_id, "target": target.value}


@router.post("/inference/unload")
async def unload_model(
    body: UnloadModelRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Evict a model from the session pool."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/unload", body.model_id, operation="WRITE", actor=_actor_label(auth))
    await _get_engine().unload_model(body.model_id)
    return {"unloaded": True, "model_id": body.model_id}


@router.post("/inference/run")
async def run_inference(
    body: RunInferenceRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Execute a single inference request."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/run", body.model_id, operation="WRITE", actor=_actor_label(auth))

    from tools.gimo_server.inference.contracts import InferenceRequest

    req = InferenceRequest(
        request_id=str(uuid.uuid4()),
        model_id=body.model_id,
        task=_parse_task(body.task),
        inputs=body.inputs,
        target_hardware=_parse_target(body.target_hardware),
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        priority=body.priority,
        timeout_seconds=body.timeout_seconds,
    )

    engine = _get_engine()
    if not engine._initialized:
        await engine.initialize()

    result = await engine.infer(req)

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "request_id": result.request_id,
        "model_id": result.model_id,
        "outputs": result.outputs,
        "hardware_used": result.hardware_used.value,
        "device_name": result.device_name,
        "execution_provider": result.execution_provider,
        "latency_ms": result.latency_ms,
        "tokens_generated": result.tokens_generated,
        "tokens_per_second": result.tokens_per_second,
        "shard_strategy": result.shard_strategy_used.value,
    }


@router.get("/inference/metrics")
async def get_inference_metrics(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Return inference telemetry metrics."""
    _require_role(auth, "operator")
    audit_log("OPS", "/ops/inference/metrics", "metrics", operation="READ", actor=_actor_label(auth))
    return _get_engine().get_metrics()
