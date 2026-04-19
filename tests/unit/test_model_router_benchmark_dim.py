"""BUGS_LATENTES §H5 — lookup per-request a BenchmarkEnrichmentService.

Antes del fix, las 14 dimensiones externas (LMArena + OpenLLM) solo se usaban
al startup para enriquecer ``ModelEntry.capabilities`` binario. ModelRouter
las ignoraba en runtime. Ahora ``_benchmark_dimension_adjustment`` consulta
per-request y ajusta success_score por la dimensión apropiada al task_type.

Tests:
- Modelo con alto score en la dimension del task → adjustment positivo
- Modelo con bajo score → adjustment negativo
- Modelo sin benchmark profile → adjustment 0 (silencioso)
- Fallback a "overall" si la dimensión específica no existe
- task_type desconocido → usa dimension "overall"
- Adjustment bounded [-0.2, 0.2]
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services.model_inventory_service import ModelEntry
from tools.gimo_server.services.model_router_service import (
    ModelRouterService,
    TASK_BENCHMARK_DIMENSION,
)


def _make_entry(model_id: str = "test-model") -> ModelEntry:
    return ModelEntry(
        model_id=model_id,
        provider_id="test",
        provider_type="test",
        is_local=True,
        quality_tier=3,
        size_gb=None,
        context_window=None,
        capabilities={"chat", "code"},
        cost_input=0.0,
        cost_output=0.0,
    )


def _fake_profile(dimensions: dict) -> MagicMock:
    prof = MagicMock()
    prof.dimensions = dimensions
    return prof


def test_high_dimension_score_yields_positive_adjustment():
    """Modelo con coding=0.9 y task code_generation → adjustment > 0."""
    entry = _make_entry("some-coder")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = _fake_profile({"coding": 0.9, "overall": 0.7})
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    # (0.9 - 0.5) * 0.4 = 0.16, bounded
    assert adj == pytest.approx(0.16, abs=0.01)
    assert any("coding" in r for r in reasons)


def test_low_dimension_score_yields_negative_adjustment():
    """Modelo con reasoning=0.2 y task security_review → adjustment < 0."""
    entry = _make_entry("weak-reasoner")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = _fake_profile({"reasoning": 0.2, "overall": 0.4})
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "security_review", entry
        )
    # (0.2 - 0.5) * 0.4 = -0.12
    assert adj == pytest.approx(-0.12, abs=0.01)


def test_missing_profile_returns_zero():
    """Modelo sin benchmark profile → adjustment 0, sin reasons."""
    entry = _make_entry("unknown-model")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = None
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    assert adj == 0.0
    assert reasons == []


def test_missing_dimension_falls_back_to_overall():
    """Si el profile no tiene la dimensión task-specific, usa overall."""
    entry = _make_entry("general-model")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        # No tiene "coding", solo "overall"
        m.return_value = _fake_profile({"overall": 0.75})
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    # (0.75 - 0.5) * 0.4 = 0.1
    assert adj == pytest.approx(0.1, abs=0.01)
    # El reason debe mencionar "overall" (el fallback usado)
    assert any("overall" in r for r in reasons)


def test_unknown_task_type_uses_overall_dimension():
    """task_type desconocido → default mapping = overall."""
    entry = _make_entry("m")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = _fake_profile({"overall": 0.6})
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "weird_custom_task", entry
        )
    assert adj == pytest.approx(0.04, abs=0.01)  # (0.6 - 0.5) * 0.4
    # Menciona overall
    assert any("overall" in r for r in reasons)


def test_adjustment_bounded_at_positive_limit():
    """Score perfecto 1.0 → adjustment saturado a +0.2."""
    entry = _make_entry("perfect")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = _fake_profile({"coding": 1.0})
        adj, _ = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    assert adj == 0.2


def test_adjustment_bounded_at_negative_limit():
    """Score 0.0 → adjustment saturado a -0.2."""
    entry = _make_entry("broken")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.return_value = _fake_profile({"coding": 0.0})
        adj, _ = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    assert adj == -0.2


def test_lookup_exception_swallowed():
    """Si lookup raise, el adjustment es 0 (no propaga)."""
    entry = _make_entry("crash")
    with patch(
        "tools.gimo_server.services.benchmark_enrichment_service.lookup_model"
    ) as m:
        m.side_effect = RuntimeError("network oops")
        adj, reasons = ModelRouterService._benchmark_dimension_adjustment(
            "code_generation", entry
        )
    assert adj == 0.0
    assert reasons == []


def test_task_benchmark_dimension_table_coverage():
    """Todos los task_types en TASK_REQUIREMENTS tienen mapping a dimension."""
    from tools.gimo_server.services.model_router_service import TASK_REQUIREMENTS

    for task_type in TASK_REQUIREMENTS.keys():
        assert task_type in TASK_BENCHMARK_DIMENSION, (
            f"task_type {task_type!r} tiene entry en TASK_REQUIREMENTS pero "
            f"no en TASK_BENCHMARK_DIMENSION — rompe el contract"
        )


def test_task_benchmark_dimension_values_are_valid():
    """Los valores del mapping están en el set de dimensiones canónicas del
    BenchmarkEnrichmentService (documentadas en docs/REPO_ATLAS)."""
    canonical = {
        "overall", "coding", "math", "reasoning", "creative",
        "long_context", "business", "science", "writing",
        "multi_step_reasoning", "general_knowledge", "expert_knowledge",
        "instruction_following", "multi_turn",
    }
    for task_type, dim in TASK_BENCHMARK_DIMENSION.items():
        assert dim in canonical, (
            f"task_type {task_type!r} mapea a {dim!r} que no es una "
            f"dimensión canónica del BenchmarkEnrichmentService"
        )
