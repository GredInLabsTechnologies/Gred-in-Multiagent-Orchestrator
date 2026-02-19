from tools.gimo_server.services.cognitive.intent_engine import RuleBasedIntentEngine


def test_detect_create_plan_intent() -> None:
    engine = RuleBasedIntentEngine()
    detected = engine.detect_intent("Crea un plan técnico para migrar el backend", {})
    assert detected.name == "CREATE_PLAN"


def test_detect_status_intent() -> None:
    engine = RuleBasedIntentEngine()
    detected = engine.detect_intent("Dame el estado actual de los runs", {})
    assert detected.name == "ASK_STATUS"


def test_detect_help_intent() -> None:
    engine = RuleBasedIntentEngine()
    detected = engine.detect_intent("help", {})
    assert detected.name == "HELP"


def test_detect_unknown_intent() -> None:
    engine = RuleBasedIntentEngine()
    detected = engine.detect_intent("texto ambiguo sin intención clara", {})
    assert detected.name == "UNKNOWN"
