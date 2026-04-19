"""BUGS_LATENTES §H6 — integración ModelRecommendationEngine en DispatchService.

Antes del fix, ``score_model()`` solo se consumía por el endpoint
``/ops/mesh/devices/{id}/model-recommendations`` — era intelligence orphan.
Ahora ``_score_devices`` acepta ``preferred_model_meta`` y ajusta el score
por FitLevel (optimal +10 / comfortable +5 / tight -5 / overload -30).

Tests:
- Sin meta: scoring idéntico al comportamiento pre-fix (sin cambios)
- Con meta: devices óptimos se prefieren sobre los tight
- Overload penalty: device que no puede con el modelo cae al final
- fit_level aparece en DispatchDecision.model_fit_level
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceCapabilities,
    DeviceMode,
    MeshDeviceInfo,
    OperationalState,
    TaskFingerprint,
)
from tools.gimo_server.services.mesh.dispatch import (
    DispatchService,
    _FIT_SCORE_BONUS,
)
from tools.gimo_server.services.mesh.model_recommendation import FitLevel
from tools.gimo_server.services.mesh.registry import MeshRegistry


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    """Registry aislado con tmpdir — evita ensuciar .orch_data real."""
    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.registry.OPS_DATA_DIR",
        tmp_path,
    )
    return MeshRegistry()


def _make_device(
    device_id: str,
    ram_total_mb: int = 8192,
    cpu_cores: int = 4,
    soc_model: str = "snapdragon 8 gen 2",
    has_gpu: bool = True,
    storage_free_mb: int = 50_000,  # 50 GB default — suficiente para modelos típicos
) -> MeshDeviceInfo:
    """Factory para devices ya en estado 'connected' y thermal-safe.

    storage_free_mb default = 50 GB para que model_recommendation.score_model()
    no degrade el fit_level por storage_ok=False cuando lo único que queremos
    probar es el RAM-based fit.
    """
    return MeshDeviceInfo(
        device_id=device_id,
        name=device_id,
        device_secret="secret",
        device_mode=DeviceMode.hybrid,
        connection_state=ConnectionState.connected,
        operational_state=OperationalState.idle,
        core_enabled=True,
        local_allow_core_control=True,
        local_allow_task_execution=True,
        cpu_percent=30.0,
        ram_percent=40.0,
        cpu_temp_c=45.0,
        battery_percent=80.0,
        battery_charging=True,
        health_score=100.0,
        last_heartbeat=datetime.now(timezone.utc),
        soc_model=soc_model,
        capabilities=DeviceCapabilities(
            arch="arm64-v8a",
            cpu_cores=cpu_cores,
            ram_total_mb=ram_total_mb,
            storage_free_mb=storage_free_mb,
            has_gpu_compute=has_gpu,
            soc_model=soc_model,
        ),
    )


def test_score_without_meta_is_backward_compat(tmp_registry):
    """Sin preferred_model_meta, scoring idéntico al comportamiento pre-H6."""
    svc = DispatchService(tmp_registry)
    d = _make_device("d1", ram_total_mb=4096)
    scored = svc._score_devices([d])
    # No hay fit_level asignado
    assert scored[0]["fit_level"] == ""
    # El score es solamente health (100) + bonuses heurísticos hardware
    # health=100, cpu<50 → +10, ram<70 → +5, battery>50 → +5 → 120
    assert scored[0]["score"] == 120


def test_score_with_meta_adds_fit_bonus(tmp_registry):
    """Con preferred_model_meta para un modelo tiny, fit debe ser optimal (+10)."""
    svc = DispatchService(tmp_registry)
    # Device con mucha RAM relativa al modelo 1B Q4
    d = _make_device("d1", ram_total_mb=12288, cpu_cores=8)
    scored = svc._score_devices(
        [d],
        model_fit_meta={
            "model_id": "tiny",
            "params_str": "1b",
            "quant_str": "q4_k_m",
            "size_bytes": 700_000_000,  # ~700 MB
        },
    )
    # fit_level debe estar populado
    assert scored[0]["fit_level"] in ("optimal", "comfortable")
    # Score incluye fit bonus (optimal +10 o comfortable +5)
    assert scored[0]["score"] > 120


def test_score_with_overload_model_penalizes_hard(tmp_registry):
    """Device con RAM limitada intentando 70B Q8 → overload → -30."""
    svc = DispatchService(tmp_registry)
    d = _make_device("weak", ram_total_mb=2048, cpu_cores=2, has_gpu=False)
    scored = svc._score_devices(
        [d],
        model_fit_meta={
            "model_id": "huge",
            "params_str": "70b",
            "quant_str": "q8_0",
            "size_bytes": 70_000_000_000,
        },
    )
    assert scored[0]["fit_level"] == "overload"
    # 120 baseline - 30 overload = 90 worst case
    assert scored[0]["score"] <= 90


def test_overload_device_sorted_last(tmp_registry):
    """Con 2 devices: uno óptimo, otro overload → el óptimo va primero."""
    svc = DispatchService(tmp_registry)
    strong = _make_device("strong", ram_total_mb=16384, cpu_cores=8, has_gpu=True)
    weak = _make_device("weak", ram_total_mb=1024, cpu_cores=2, has_gpu=False)

    scored = svc._score_devices(
        [weak, strong],  # orden input NO garantiza orden output
        model_fit_meta={
            "model_id": "mid",
            "params_str": "7b",
            "quant_str": "q4_k_m",
            "size_bytes": 4_000_000_000,
        },
    )

    # El strong debe estar primero
    assert scored[0]["device"].device_id == "strong"
    assert scored[1]["device"].device_id == "weak"
    # El weak debe marcarse overload (no puede con 7B en 1GB RAM)
    assert scored[1]["fit_level"] == "overload"


def test_device_without_capabilities_skips_fit(tmp_registry):
    """Si device no tiene DeviceCapabilities poblado, fit es None → sin bonus."""
    svc = DispatchService(tmp_registry)
    d = _make_device("bare")
    d.capabilities = None  # simular device que no reportó capabilities
    scored = svc._score_devices(
        [d],
        model_fit_meta={
            "model_id": "any",
            "params_str": "3b",
            "quant_str": "q4_k_m",
            "size_bytes": 2_000_000_000,
        },
    )
    # fit_level vacío (no evaluado) → score igual al baseline
    assert scored[0]["fit_level"] == ""
    assert scored[0]["score"] == 120  # sin bonus ni penalty


def test_dispatch_decision_surfaces_fit_level(tmp_registry):
    """DispatchDecision.model_fit_level lleva el valor del scoring."""
    svc = DispatchService(tmp_registry)
    d = _make_device("d1", ram_total_mb=12288, cpu_cores=8)
    tmp_registry.save_device(d)

    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    decision = svc.dispatch(
        fingerprint=fp,
        mesh_enabled=True,
        preferred_model_meta={
            "model_id": "tiny",
            "params_str": "1b",
            "quant_str": "q4_k_m",
            "size_bytes": 700_000_000,
        },
    )
    assert decision.device_id == "d1"
    assert decision.model_fit_level in ("optimal", "comfortable")
    # reason incluye suffix fit=
    assert "fit=" in decision.reason


def test_fit_score_bonus_constants():
    """Los valores del mapping son los documentados en el contract."""
    assert _FIT_SCORE_BONUS[FitLevel.optimal] == 10.0
    assert _FIT_SCORE_BONUS[FitLevel.comfortable] == 5.0
    assert _FIT_SCORE_BONUS[FitLevel.tight] == -5.0
    assert _FIT_SCORE_BONUS[FitLevel.overload] == -30.0
