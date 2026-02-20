from tools.gimo_server.services.cognitive.direct_response_engine import RuleBasedDirectResponseEngine
from tools.gimo_server.services.cognitive.models import DetectedIntent


def test_direct_response_bypass_for_help_and_status() -> None:
    engine = RuleBasedDirectResponseEngine()
    assert engine.can_bypass_llm(DetectedIntent(name="HELP"), {}) is True
    assert engine.can_bypass_llm(DetectedIntent(name="ASK_STATUS"), {}) is True
    assert engine.can_bypass_llm(DetectedIntent(name="CREATE_PLAN"), {}) is False


def test_build_execution_plan_for_create_plan() -> None:
    engine = RuleBasedDirectResponseEngine()
    draft = engine.build_execution_plan(
        DetectedIntent(name="CREATE_PLAN"),
        {"prompt": "Crea un plan técnico para observabilidad"},
    )
    assert "PLAN PROPUESTO" in draft.content
    assert "Contexto base" in draft.content
