import math
from tools.gimo_server.services.institutional_memory_service import InstitutionalMemoryService
from tests.unit.test_services import _StubStorage, _StubGicsBridge

# ── Institutional Memory ──────────────────────────────────


def test_institutional_memory_suggests_promote_auto_approve():
    svc = InstitutionalMemoryService(_StubStorage([{"dimension_key": "f|s/a.py|sonnet|add", "approvals": 25, "rejections": 1, "failures": 0, "score": 0.93, "policy": "require_review"}]))
    suggestions = svc.generate_suggestions(limit=10)
    assert len(suggestions) == 1
    assert suggestions[0]["action"] == "promote_auto_approve"


def test_institutional_memory_suggests_block_on_failure_burst():
    svc = InstitutionalMemoryService(_StubStorage([{"dimension_key": "x", "approvals": 0, "rejections": 0, "failures": 10, "score": 0.1, "policy": "r"}]))
    suggestions = svc.generate_suggestions(limit=10)
    assert len(suggestions) == 1
    assert suggestions[0]["action"] == "block_dimension"


# ── OpsService GICS Bridge ────────────────────────────────


def test_ops_service_gics_bridge_seed_record_get():
    from tools.gimo_server.services.ops import OpsService

    gics = _StubGicsBridge()
    OpsService.set_gics(gics)

    seeded = OpsService.seed_model_priors(
        provider_type="openai",
        model_id="gpt-4o",
        prior_scores={"coding": 0.9},
        metadata={"source": "test"},
    )
    assert seeded is not None and seeded["provider_type"] == "openai"

    outcome = OpsService.record_model_outcome(
        provider_type="openai",
        model_id="gpt-4o",
        success=True,
        latency_ms=123.0,
        cost_usd=0.01,
        task_type="coding",
    )
    assert outcome is not None and outcome["success"] is True

    reliability = OpsService.get_model_reliability(provider_type="openai", model_id="gpt-4o")
    assert reliability is not None and math.isclose(reliability["score"], 0.77)

    OpsService.set_gics(None)
