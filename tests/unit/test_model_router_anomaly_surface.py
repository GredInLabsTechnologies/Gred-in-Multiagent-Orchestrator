"""BUGS_LATENTES §H7 — GICS anomaly surface en ModelSelectionDecision.

Por diseño, GICS signals son advisory (memory feedback_constraint_compiler_philosophy).
Este fix NO cambia la selección: el modelo anómalo sigue siendo elegible.
Lo que sí cambia es que la ``ModelSelectionDecision`` ahora lleva
``anomaly_detected`` + ``anomaly_alternative`` — el caller / UI puede
mostrar advisory al operator.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.models.provider import ProviderRoleBinding
from tools.gimo_server.services.model_inventory_service import ModelEntry
from tools.gimo_server.services.model_router_service import ModelRouterService


def _entry(model_id: str, quality_tier: int = 3) -> ModelEntry:
    return ModelEntry(
        model_id=model_id,
        provider_id="openai",
        provider_type="openai",
        is_local=False,
        quality_tier=quality_tier,
        size_gb=None,
        context_window=None,
        capabilities={"chat"},
        cost_input=0.0,
        cost_output=0.0,
    )


def _binding(model: str) -> ProviderRoleBinding:
    return ProviderRoleBinding(provider_id="openai", model=model)


def test_decision_flags_anomaly_when_gics_reports():
    """Si el modelo elegido tiene gics.anomaly=True, flag se propaga."""
    anomalous = _entry("anomalous-model")
    reliability = {"score": 0.5, "anomaly": True}

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        return_value=reliability,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                return_value=anomalous,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(_binding("anomalous-model"), anomalous)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=[_binding("anomalous-model")],
                    )

    assert decision.anomaly_detected is True


def test_decision_no_anomaly_when_clean():
    """Reliability sin anomaly → flag False (default)."""
    clean = _entry("clean-model")
    reliability = {"score": 0.8, "anomaly": False}

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        return_value=reliability,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                return_value=clean,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(_binding("clean-model"), clean)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=[_binding("clean-model")],
                    )

    assert decision.anomaly_detected is False
    assert decision.anomaly_alternative == ""


def test_anomaly_alternative_suggests_clean_candidate():
    """Cuando el elegido es anómalo y hay otro limpio, se sugiere como alternative."""
    anom = _entry("anom", quality_tier=5)
    clean = _entry("clean", quality_tier=3)

    def fake_reliability(provider_type, model_id):
        if model_id == "anom":
            return {"score": 0.5, "anomaly": True}
        return {"score": 0.7, "anomaly": False}

    bindings = [_binding("anom"), _binding("clean")]

    def fake_inventory(binding):
        return anom if binding.model == "anom" else clean

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        side_effect=fake_reliability,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                side_effect=fake_inventory,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(bindings[0], anom), (bindings[1], clean)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=bindings,
                    )

    # El elegido es el anom (quality_tier=5 + bonus > -0.25 penalty)
    # o puede ser clean (gics_reliability 0.7 * 0.4 = +0.08 vs anom -0.25).
    # Da igual cuál gane — lo que importa es:
    if decision.model == "anom":
        assert decision.anomaly_detected is True
        assert decision.anomaly_alternative == "clean"
    else:
        # si clean gana, el anomaly flag del selected es False
        assert decision.anomaly_detected is False
        assert decision.anomaly_alternative == ""


def test_reason_includes_anomaly_marker():
    """El reason string contiene 'gics_anomaly_detected=true' cuando aplica."""
    anomalous = _entry("anomalous-model")
    reliability = {"score": 0.5, "anomaly": True}

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        return_value=reliability,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                return_value=anomalous,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(_binding("anomalous-model"), anomalous)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=[_binding("anomalous-model")],
                    )

    assert "gics_anomaly_detected=true" in decision.reason


def test_anomaly_does_not_exclude_model():
    """Memory invariant: anomaly signals NEVER override policy — still selectable."""
    only_anom = _entry("only-anom")
    reliability = {"score": 0.5, "anomaly": True}

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        return_value=reliability,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                return_value=only_anom,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(_binding("only-anom"), only_anom)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=[_binding("only-anom")],
                    )

    # No exclusión — el modelo se selecciona aunque sea el único y anómalo
    assert decision.model == "only-anom"
    assert decision.anomaly_detected is True


def test_decision_fields_default_safe():
    """Sin reliability data, defaults limpian: no anomaly, no alternative."""
    clean = _entry("clean")

    with patch(
        "tools.gimo_server.services.ops_service.OpsService.get_model_reliability",
        return_value=None,
    ):
        with patch(
            "tools.gimo_server.services.capability_profile_service.CapabilityProfileService.get_capability",
            return_value=None,
        ):
            with patch.object(
                ModelRouterService, "_inventory_entry_for_binding",
                return_value=clean,
            ):
                with patch.object(
                    ModelRouterService, "_filter_binding_candidates_for_task",
                    return_value=([(_binding("clean"), clean)], [], "chat", 2),
                ):
                    decision = ModelRouterService.choose_binding_from_candidates(
                        task_type="default",
                        candidates=[_binding("clean")],
                    )

    assert decision.anomaly_detected is False
    assert decision.anomaly_alternative == ""
