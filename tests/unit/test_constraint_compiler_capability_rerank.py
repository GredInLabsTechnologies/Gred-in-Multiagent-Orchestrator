"""BUGS_LATENTES §H4 — ConstraintCompiler rerank bindings por CapabilityProfile.

Antes del fix, ConstraintCompiler no consultaba CapabilityProfileService —
bindings iban en orden del ProviderTopology. Ahora ``_rerank_bindings_by_capability``
prioriza bindings con mejor success_rate en el task_type, sin exclusión.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services.constraint_compiler_service import (
    ConstraintCompilerService,
)


@dataclass
class _FakeBinding:
    """Minimal stand-in para ProviderRoleBinding."""
    provider_id: str
    model: str


def _capability(success_rate: float, samples: int = 10) -> MagicMock:
    cap = MagicMock()
    cap.success_rate = success_rate
    cap.samples = samples
    return cap


def test_rerank_prefers_higher_success_rate():
    bindings = [
        _FakeBinding("openai", "low-perf"),
        _FakeBinding("anthropic", "high-perf"),
    ]

    def fake_get_cap(provider_type, model_id, task_type):
        if model_id == "high-perf":
            return _capability(0.9)
        if model_id == "low-perf":
            return _capability(0.3)
        return None

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        side_effect=fake_get_cap,
    ):
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "code_generation"
        )

    assert reranked[0].model == "high-perf"
    assert reranked[1].model == "low-perf"


def test_rerank_puts_no_samples_last():
    """Bindings sin track record quedan DESPUÉS de los que sí tienen."""
    bindings = [
        _FakeBinding("provider_a", "no-track"),  # no samples
        _FakeBinding("provider_b", "tracked"),    # has history
    ]

    def fake_get_cap(provider_type, model_id, task_type):
        if model_id == "tracked":
            return _capability(0.6)
        return None  # no data

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        side_effect=fake_get_cap,
    ):
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "default"
        )

    assert reranked[0].model == "tracked"
    assert reranked[1].model == "no-track"


def test_rerank_never_excludes():
    """Aunque todos tengan score bajo, se preservan todos los candidatos."""
    bindings = [
        _FakeBinding("p", "a"),
        _FakeBinding("p", "b"),
        _FakeBinding("p", "c"),
    ]

    def fake_get_cap(provider_type, model_id, task_type):
        return _capability(0.1)  # all terrible

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        side_effect=fake_get_cap,
    ):
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "default"
        )

    assert len(reranked) == 3
    assert {b.model for b in reranked} == {"a", "b", "c"}


def test_rerank_ignores_low_sample_count():
    """Capability con samples < 2 se trata como sin track record."""
    bindings = [
        _FakeBinding("p", "one_sample"),  # samples=1
        _FakeBinding("p", "many_samples"),  # samples=5
    ]

    def fake_get_cap(provider_type, model_id, task_type):
        if model_id == "one_sample":
            return _capability(1.0, samples=1)  # perfect but insufficient data
        return _capability(0.5, samples=5)

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        side_effect=fake_get_cap,
    ):
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "default"
        )

    # many_samples wins even with lower success_rate because it has enough data
    assert reranked[0].model == "many_samples"


def test_rerank_survives_capability_exception():
    """Si CapabilityProfileService raise, no rompe el compile."""
    bindings = [
        _FakeBinding("p", "a"),
        _FakeBinding("p", "b"),
    ]

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        side_effect=RuntimeError("gics offline"),
    ):
        # No debe raise — todos tratados como score 0
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "default"
        )
    assert len(reranked) == 2


def test_rerank_stable_for_equal_scores():
    """Bindings con score idéntico preservan orden original (stable sort)."""
    bindings = [
        _FakeBinding("a", "m1"),
        _FakeBinding("b", "m2"),
        _FakeBinding("c", "m3"),
    ]

    with patch(
        "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
        return_value=None,  # todos sin track
    ):
        reranked = ConstraintCompilerService._rerank_bindings_by_capability(
            bindings, "default"
        )

    assert reranked == bindings  # orden preservado
