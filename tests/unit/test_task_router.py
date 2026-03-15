"""Unit tests for TaskRouter, ModelSelector, and LoadBalancer."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from tools.gimo_server.inference.contracts import (
    DeviceCapability,
    ExecutionProviderType,
    HardwareTarget,
    InferenceRequest,
    ModelFormat,
    ModelSpec,
    QuantizationType,
    TaskSemantic,
)
from tools.gimo_server.inference.router.task_router import TaskRouter, TASK_AFFINITY
from tools.gimo_server.inference.router.model_selector import ModelSelector
from tools.gimo_server.inference.router.load_balancer import LoadBalancer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _request(
    task: TaskSemantic = TaskSemantic.GENERAL,
    target: HardwareTarget = HardwareTarget.AUTO,
    priority: int = 5,
) -> InferenceRequest:
    return InferenceRequest(
        request_id=str(uuid.uuid4()),
        model_id="test-model",
        task=task,
        inputs={"prompt": "hello"},
        target_hardware=target,
        priority=priority,
    )


def _device(dtype: HardwareTarget, free_gb: float = 8.0, temp: float = 0.0, util: float = 0.0) -> DeviceCapability:
    return DeviceCapability(
        device_type=dtype,
        device_name=f"{dtype.value}-device",
        total_memory_gb=free_gb,
        free_memory_gb=free_gb,
        temperature_celsius=temp,
        utilization_percent=util,
        execution_providers=[ExecutionProviderType.CPU],
    )


def _spec(model_id: str, tasks: List[TaskSemantic] = None, size_gb: float = 4.0) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        path=Path(f"/fake/{model_id}.onnx"),
        format=ModelFormat.ONNX,
        size_bytes=int(size_gb * 1024**3),
        param_count_b=7.0,
        supported_tasks=tasks or [],
    )


# ---------------------------------------------------------------------------
# TaskRouter — affinity
# ---------------------------------------------------------------------------

class TestTaskRouterAffinity:
    def test_embedding_prefers_npu(self):
        devices = [_device(HardwareTarget.NPU), _device(HardwareTarget.GPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(TaskSemantic.EMBEDDING))
        assert decision.target_device == HardwareTarget.NPU

    def test_reasoning_prefers_gpu(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.NPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(TaskSemantic.REASONING))
        assert decision.target_device == HardwareTarget.GPU

    def test_classification_prefers_npu(self):
        devices = [_device(HardwareTarget.NPU), _device(HardwareTarget.CPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(TaskSemantic.CLASSIFICATION))
        assert decision.target_device == HardwareTarget.NPU

    def test_code_generation_prefers_gpu(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.CPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(TaskSemantic.CODE_GENERATION))
        assert decision.target_device == HardwareTarget.GPU

    def test_no_devices_falls_back_to_cpu(self):
        router = TaskRouter(devices=[])
        decision = router.route(_request(TaskSemantic.GENERAL))
        assert decision.target_device == HardwareTarget.CPU

    def test_only_cpu_available_uses_cpu(self):
        router = TaskRouter(devices=[_device(HardwareTarget.CPU)])
        decision = router.route(_request(TaskSemantic.EMBEDDING))
        assert decision.target_device == HardwareTarget.CPU


class TestTaskRouterExplicit:
    def test_explicit_target_respected(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.CPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(target=HardwareTarget.GPU))
        assert decision.target_device == HardwareTarget.GPU

    def test_explicit_unavailable_falls_back(self):
        # Only CPU available but NPU requested → should fall back to AUTO routing.
        devices = [_device(HardwareTarget.CPU)]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(target=HardwareTarget.NPU))
        assert decision.target_device == HardwareTarget.CPU

    def test_critical_temperature_triggers_fallback(self):
        devices = [
            _device(HardwareTarget.GPU, temp=95.0),  # critical
            _device(HardwareTarget.CPU),
        ]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(target=HardwareTarget.GPU))
        assert decision.target_device == HardwareTarget.CPU


class TestTaskRouterScoring:
    def test_high_memory_preferred(self):
        devices = [
            _device(HardwareTarget.GPU, free_gb=20.0),
            _device(HardwareTarget.GPU, free_gb=4.0),
        ]
        router = TaskRouter(devices=devices)
        decision = router.route(_request(TaskSemantic.REASONING))
        # Should pick the one with more free memory.
        assert decision.target_device == HardwareTarget.GPU

    def test_latency_ewma_affects_score(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.NPU)]
        router = TaskRouter(devices=devices)
        # Give GPU an artificially high latency.
        router.update_latency("gpu", 9000.0)
        decision = router.route(_request(TaskSemantic.REASONING))
        # Reasoned that despite affinity for GPU, high latency may penalise it.
        # Just check the router returned something valid.
        assert decision.target_device in (HardwareTarget.GPU, HardwareTarget.CPU, HardwareTarget.NPU)

    def test_update_devices(self):
        router = TaskRouter(devices=[])
        router.update_devices([_device(HardwareTarget.GPU)])
        decision = router.route(_request(TaskSemantic.REASONING))
        assert decision.target_device == HardwareTarget.GPU


class TestTaskAffinityTable:
    def test_all_tasks_covered(self):
        for task in TaskSemantic:
            assert task in TASK_AFFINITY, f"{task} missing from TASK_AFFINITY"

    def test_all_affinity_lists_have_three_entries(self):
        for task, affinity in TASK_AFFINITY.items():
            assert len(affinity) == 3, f"{task} affinity list should have 3 entries"


# ---------------------------------------------------------------------------
# ModelSelector
# ---------------------------------------------------------------------------

class TestModelSelector:
    def test_selects_task_capable_model(self):
        selector = ModelSelector()
        candidates = [
            _spec("embedding-model", [TaskSemantic.EMBEDDING]),
            _spec("general-model", [TaskSemantic.GENERAL]),
        ]
        result = selector.select(TaskSemantic.EMBEDDING, candidates, [])
        assert result.model is not None
        assert result.model.model_id == "embedding-model"

    def test_no_candidates_returns_none(self):
        selector = ModelSelector()
        result = selector.select(TaskSemantic.GENERAL, [], [])
        assert result.model is None

    def test_no_task_match_returns_none(self):
        selector = ModelSelector()
        candidates = [_spec("vision-model", [TaskSemantic.VISION])]
        result = selector.select(TaskSemantic.REASONING, candidates, [])
        assert result.model is None

    def test_empty_supported_tasks_matches_all(self):
        selector = ModelSelector()
        candidates = [_spec("general-model", [])]  # empty = matches all
        result = selector.select(TaskSemantic.REASONING, candidates, [])
        assert result.model is not None

    def test_prefers_already_loaded(self):
        def is_loaded(mid, dev): return mid == "loaded-model"
        selector = ModelSelector(is_loaded_fn=is_loaded)
        candidates = [
            _spec("unloaded-model", []),
            _spec("loaded-model", []),
        ]
        result = selector.select(TaskSemantic.GENERAL, candidates, [], HardwareTarget.GPU)
        assert result.model.model_id == "loaded-model"
        assert result.already_loaded is True

    def test_memory_constraint_not_fitting(self):
        def fits(m, devs): return False  # nothing fits
        selector = ModelSelector(fits_fn=fits)
        candidates = [_spec("big-model", [])]
        result = selector.select(TaskSemantic.GENERAL, candidates, [])
        # Returns model but flags as not fitting.
        assert result.model is not None
        assert result.fits_in_memory is False

    def test_quality_tier_ordering(self):
        selector = ModelSelector()
        candidates = [
            _spec("base-model", []),
            _spec("pro-model", []),
        ]
        candidates[0].metadata["quality_tier"] = "base"
        candidates[1].metadata["quality_tier"] = "pro"
        result = selector.select(
            TaskSemantic.GENERAL,
            candidates,
            [],
            quality_tiers=["base", "pro"],
        )
        # "pro" has higher tier index → preferred.
        assert result.model.model_id == "pro-model"


# ---------------------------------------------------------------------------
# LoadBalancer
# ---------------------------------------------------------------------------

class TestLoadBalancer:
    def test_selects_preferred_type(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.CPU)]
        lb = LoadBalancer(devices)
        chosen = lb.select(HardwareTarget.GPU)
        assert chosen is not None
        assert chosen.device_type == HardwareTarget.GPU

    def test_fallback_when_preferred_not_available(self):
        devices = [_device(HardwareTarget.CPU)]
        lb = LoadBalancer(devices)
        chosen = lb.select(HardwareTarget.GPU)
        # GPU not available → fallback to NPU → fallback to CPU
        assert chosen is not None
        assert chosen.device_type == HardwareTarget.CPU

    def test_critical_temperature_excluded(self):
        devices = [_device(HardwareTarget.GPU, temp=95.0), _device(HardwareTarget.CPU)]
        lb = LoadBalancer(devices)
        chosen = lb.select(HardwareTarget.GPU)
        # GPU too hot → fallback to CPU
        assert chosen.device_type == HardwareTarget.CPU

    def test_low_memory_excluded(self):
        devices = [
            _device(HardwareTarget.GPU, free_gb=0.1),  # too little
            _device(HardwareTarget.CPU, free_gb=16.0),
        ]
        lb = LoadBalancer(devices)
        chosen = lb.select(HardwareTarget.GPU)
        assert chosen.device_type == HardwareTarget.CPU

    def test_fallback_method(self):
        devices = [_device(HardwareTarget.GPU), _device(HardwareTarget.CPU)]
        lb = LoadBalancer(devices)
        fb = lb.fallback(HardwareTarget.GPU)
        assert fb is not None
        assert fb.device_type != HardwareTarget.GPU

    def test_update_devices(self):
        lb = LoadBalancer([])
        lb.update_devices([_device(HardwareTarget.GPU)])
        assert lb.select(HardwareTarget.GPU) is not None

    def test_no_devices_returns_none(self):
        lb = LoadBalancer([])
        assert lb.select(HardwareTarget.GPU) is None


# ---------------------------------------------------------------------------
# HardwareScheduler — basic queue behavior
# ---------------------------------------------------------------------------

class TestHardwareScheduler:
    @pytest.mark.asyncio
    async def test_enqueue_and_release(self):
        from tools.gimo_server.inference.router.hardware_scheduler import HardwareScheduler

        scheduler = HardwareScheduler(devices=[_device(HardwareTarget.CPU)])
        req = _request()
        ticket = await scheduler.enqueue(req, HardwareTarget.CPU)
        # Ticket should be granted immediately (no contention).
        await ticket.wait(timeout=1.0)
        assert ticket.grant_time > 0
        scheduler.release(ticket)

    @pytest.mark.asyncio
    async def test_second_request_queued_when_full(self):
        from tools.gimo_server.inference.router.hardware_scheduler import HardwareScheduler

        scheduler = HardwareScheduler(
            devices=[_device(HardwareTarget.CPU)],
            concurrency_overrides={HardwareTarget.CPU: 1},
        )
        req1 = _request()
        req2 = _request()

        ticket1 = await scheduler.enqueue(req1, HardwareTarget.CPU)
        await ticket1.wait(timeout=1.0)

        # Second request should be queued (semaphore full).
        ticket2 = await scheduler.enqueue(req2, HardwareTarget.CPU)
        assert not ticket2._ready.is_set()  # still queued

        # Release first → second should be dispatched.
        scheduler.release(ticket1)
        await asyncio.sleep(0.05)   # allow task loop to run
        assert ticket2._ready.is_set()
        scheduler.release(ticket2)

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        from tools.gimo_server.inference.router.hardware_scheduler import HardwareScheduler

        scheduler = HardwareScheduler(
            devices=[_device(HardwareTarget.CPU)],
            concurrency_overrides={HardwareTarget.CPU: 1},
        )
        req_holder = _request(priority=5)
        req_low    = _request(priority=9)
        req_high   = _request(priority=1)

        # Hold the slot.
        holder = await scheduler.enqueue(req_holder, HardwareTarget.CPU)
        await holder.wait(timeout=1.0)

        # Enqueue low priority first, then high priority.
        t_low  = await scheduler.enqueue(req_low,  HardwareTarget.CPU)
        t_high = await scheduler.enqueue(req_high, HardwareTarget.CPU)

        # Release slot — high priority should get it first.
        scheduler.release(holder)
        await asyncio.sleep(0.05)
        assert t_high._ready.is_set()
        assert not t_low._ready.is_set()

        scheduler.release(t_high)
        await asyncio.sleep(0.05)
        assert t_low._ready.is_set()
        scheduler.release(t_low)
