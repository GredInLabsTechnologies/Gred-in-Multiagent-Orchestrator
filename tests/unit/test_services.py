import pytest
import asyncio
import math
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch
from tools.gimo_server.ops_models import WorkflowNode, TrustEvent, EvalDataset, EvalGateConfig, EvalGoldenCase, EvalJudgeConfig, WorkflowGraph
from tools.gimo_server.services.model_router_service import ModelRouterService, RoutingDecision
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.recommendation_service import RecommendationService
from tools.gimo_server.services.quality_service import QualityService
from tools.gimo_server.services.llm_cache import NormalizedLLMCache
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.institutional_memory_service import InstitutionalMemoryService
from tools.gimo_server.services.evals_service import EvalsService

# ── Storage Mock ──────────────────────────────────────────

class MockGics:
    def __init__(self): self.data = {}
    def put(self, key, value): self.data[key] = value
    def get(self, key):
        if key in self.data: return {"key": key, "fields": self.data[key]}
        return None
    def scan(self, prefix="", include_fields=False):
        return [{"key": k, "fields": v} for k, v in self.data.items() if k.startswith(prefix)]

class _StubStorage:
    def __init__(self, records): self._records = records
    def list_trust_records(self, limit: int = 100): return self._records[:limit]


class _StubGicsBridge:
    def __init__(self):
        self.calls = []
        self.reliability = {"score": 0.77, "samples": 11}

    def seed_model_prior(self, **kwargs):
        self.calls.append(("seed", kwargs))
        return {"ok": True, **kwargs}

    def record_model_outcome(self, **kwargs):
        self.calls.append(("record", kwargs))
        return {"ok": True, **kwargs}

    def get_model_reliability(self, **kwargs):
        self.calls.append(("get", kwargs))
        return dict(self.reliability)

# ── Model Router & Budget ─────────────────────────────────

@pytest.mark.asyncio
class TestModelRouter:
    async def test_policy_routing(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "security_review"})
        decision = await router.choose_model(node, _state={})
        assert decision.model != "unknown"
        assert decision.tier >= 1

    async def test_budget_degradation(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "code_generation"})
        state = {"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 9.5}}
        decision = await router.choose_model(node, _state=state)
        assert decision.model != "unknown"

    async def test_phase6_forced_local_for_security_change(self):
        await asyncio.sleep(0)
        decision = ModelRouterService.resolve_phase6_strategy(
            intent_effective="SECURITY_CHANGE",
            path_scope=["tools/gimo_server/security/auth.py"],
            primary_failure_reason="",
        )
        assert decision.final_model_used == ModelRouterService.PHASE6_FALLBACK_MODEL
        assert decision.fallback_used is False
        assert decision.strategy_reason == "forced_local_only"

    async def test_phase6_400_never_fallback(self):
        await asyncio.sleep(0)
        decision = ModelRouterService.resolve_phase6_strategy(
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
            primary_failure_reason="400",
        )
        assert decision.fallback_used is False
        assert decision.final_model_used == ModelRouterService.PHASE6_PRIMARY_MODEL

    async def test_phase6_429_uses_fallback(self):
        await asyncio.sleep(0)
        decision = ModelRouterService.resolve_phase6_strategy(
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
            primary_failure_reason="429",
        )
        assert decision.fallback_used is True
        assert decision.final_model_used == ModelRouterService.PHASE6_FALLBACK_MODEL
        assert decision.final_status == "FALLBACK_MODEL_USED"

    async def test_phase6_deterministic_decision(self):
        await asyncio.sleep(0)
        kwargs = {
            "intent_effective": "SAFE_REFACTOR",
            "path_scope": ["tools/gimo_server/services/provider_service.py"],
            "primary_failure_reason": "timeout",
        }
        a = ModelRouterService.resolve_phase6_strategy(**kwargs)
        b = ModelRouterService.resolve_phase6_strategy(**kwargs)
        assert a.strategy_decision_id == b.strategy_decision_id
        assert a.final_model_used == b.final_model_used


def test_resolve_tier_routing_uses_roles_schema_first():
    cfg = SimpleNamespace(
        providers={
            "orch-main": {"model": "gpt-4o"},
            "wk-1": {"model": "qwen2.5-coder:7b"},
        },
        roles=SimpleNamespace(
            orchestrator=SimpleNamespace(provider_id="orch-main", model="gpt-4o"),
            workers=[SimpleNamespace(provider_id="wk-1", model="qwen2.5-coder:7b")],
        ),
        orchestrator_provider="legacy-orch",
        orchestrator_model="legacy-model",
        worker_provider="legacy-worker",
        worker_model="legacy-worker-model",
    )

    orch_provider, orch_model = ModelRouterService.resolve_tier_routing("analysis", cfg)
    worker_provider, worker_model = ModelRouterService.resolve_tier_routing("code_generation", cfg)

    assert orch_provider == "orch-main"
    assert orch_model == "gpt-4o"
    assert worker_provider == "wk-1"
    assert worker_model == "qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_recommendation_service_returns_structured_topology():
    class _FakeMonitor:
        @staticmethod
        def get_current_state():
            return {
                "gpu_vendor": "none",
                "gpu_vram_gb": 0.0,
                "gpu_vram_free_gb": 0.0,
                "total_ram_gb": 16.0,
                "wsl2_available": False,
            }

    with patch("tools.gimo_server.services.recommendation_service.HardwareMonitorService.get_instance", return_value=_FakeMonitor()):
        result = await RecommendationService.get_recommendation()

    assert "orchestrator" in result
    assert "worker_pool" in result
    assert result["orchestrator"]["provider"] == result["provider"]
    assert isinstance(result["worker_pool"], list)
    assert result["worker_pool"][0]["count_hint"] == result["workers"]


@pytest.mark.asyncio
async def test_recommendation_service_separates_orchestrator_and_workers_with_reliability():
    class _FakeMonitor:
        @staticmethod
        def get_current_state():
            return {
                "gpu_vendor": "nvidia",
                "gpu_vram_gb": 40.0,
                "gpu_vram_free_gb": 18.0,
                "total_ram_gb": 64.0,
                "wsl2_available": False,
            }

    catalog_models = [
        SimpleNamespace(id="qwen-reasoner-coder:32b", size="32b", capabilities=["code", "reasoning"]),
        SimpleNamespace(id="qwen-coder:7b", size="7b", capabilities=["code"]),
        SimpleNamespace(id="llama-coder:13b", size="13b", capabilities=["code"]),
    ]

    def _fake_reliability(*, provider_type: str, model_id: str):
        if model_id == "qwen-coder:7b":
            return {"score": 0.95, "anomaly": False}
        if model_id == "qwen-reasoner-coder:32b":
            return {"score": 0.90, "anomaly": False}
        if model_id == "llama-coder:13b":
            return {"score": 0.70, "anomaly": False}
        return {"score": 0.50, "anomaly": False}

    with patch("tools.gimo_server.services.recommendation_service.HardwareMonitorService.get_instance", return_value=_FakeMonitor()):
        with patch("tools.gimo_server.services.recommendation_service.ProviderCatalogService.list_available_models", new=AsyncMock(return_value=(catalog_models, []))):
            with patch("tools.gimo_server.services.recommendation_service.OpsService.get_model_reliability", side_effect=_fake_reliability):
                result = await RecommendationService.get_recommendation()

    assert result["orchestrator"]["provider"] == "ollama"
    assert result["orchestrator"]["model"] == "qwen-reasoner-coder:32b"
    assert result["worker_pool"][0]["model"] == "qwen-coder:7b"
    assert result["worker_pool"][0]["count_hint"] >= 1


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_policy_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("policy check failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_schema_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("schema validation failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_no_fallback_on_merge_gate_error():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = RuntimeError("merge gate failed")
        with pytest.raises(RuntimeError) as exc:
            await ProviderService.static_generate_phase6_strategy(
                prompt="hola",
                context={},
                intent_effective="SAFE_REFACTOR",
                path_scope=["tools/gimo_server/services/ops_service.py"],
            )
        assert "PHASE6_NO_FALLBACK" in str(exc.value)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_fallback_on_429():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        import httpx

        req = httpx.Request("POST", "http://localhost/v1/chat/completions")
        resp = httpx.Response(429, request=req)
        mock_generate.side_effect = [
            httpx.HTTPStatusError("too many requests", request=req, response=resp),
            httpx.HTTPStatusError("too many requests", request=req, response=resp),
            {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0},
        ]

        result = await ProviderService.static_generate_phase6_strategy(
            prompt="hola",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )

        assert result["fallback_used"] is True
        assert result["failure_reason"] == "429"
        assert result["execution_decision"] == "FALLBACK_MODEL_USED"
        assert isinstance(result["fallback_count_window"], int)


@pytest.mark.asyncio
async def test_phase6_provider_strategy_fallback_on_5xx():
    with patch.object(ProviderService, "static_generate", new_callable=AsyncMock) as mock_generate:
        import httpx

        req = httpx.Request("POST", "http://localhost/v1/chat/completions")
        resp = httpx.Response(503, request=req)
        mock_generate.side_effect = [
            httpx.HTTPStatusError("service unavailable", request=req, response=resp),
            httpx.HTTPStatusError("service unavailable", request=req, response=resp),
            {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0},
        ]

        result = await ProviderService.static_generate_phase6_strategy(
            prompt="hola",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )

        assert result["fallback_used"] is True
        assert result["failure_reason"] == "5xx"
        assert result["execution_decision"] == "FALLBACK_MODEL_USED"

# ── Quality Service ───────────────────────────────────────

class TestQualityService:
    @pytest.mark.parametrize("text,expected_score,alert", [
        ("High quality content here.", 100, None),
        ("", 0, "empty_output"),
        ("I am sorry, I cannot fulfill this.", 40, "has_error_phrase")
    ])
    def test_output_analysis(self, text, expected_score, alert):
        res = QualityService.analyze_output(text)
        if alert: assert alert in res.alerts or res.heuristics.get(alert)
        if expected_score == 100: assert res.score == 100
        else: assert res.score < 100

# ── Cache Logic ───────────────────────────────────────────

class TestLLMCache:
    def test_normalization(self, tmp_path):
        cache = NormalizedLLMCache(tmp_path)
        assert cache.normalize_prompt("\u201cSmart Quote\u201d") == "smart quote"
        assert cache.normalize_prompt("Hello World!!!") == "hello world"

    def test_hit_miss(self, tmp_path):
        cache = NormalizedLLMCache(tmp_path)
        cache.set("prompt", "task", {"success": True, "response": "OK"})
        assert cache.get("  PROMPT!!  ", "task")["result"] == "OK"

# ── Storage Service ───────────────────────────────────────

class TestStorageService:
    def test_workflow_roundtrip(self):
        storage = StorageService(gics=MockGics())
        storage.save_workflow("wf1", '{"id": "wf1", "nodes": []}')
        assert storage.get_workflow("wf1")["id"] == "wf1"

    def test_idempotency(self):
        storage = StorageService(gics=MockGics())
        assert storage.register_tool_call_idempotency_key(idempotency_key="k", tool="t", context="c") is True
        assert storage.register_tool_call_idempotency_key(idempotency_key="k", tool="t", context="c") is False

# ── File & Git Services ───────────────────────────────────

class TestFileService:
    def test_audit_tail(self, tmp_path):
        log = tmp_path / "audit.log"
        log.write_text("line1\nline2")
        with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", log):
            from tools.gimo_server.services.file_service import FileService
            assert FileService.tail_audit_lines(limit=1) == ["line2"]

class TestGitService:
    def test_list_repos(self, tmp_path):
        from tools.gimo_server.services.git_service import GitService
        (tmp_path / "repo1").mkdir()
        repos = GitService.list_repos(tmp_path)
        assert len(repos) >= 1

# ── System Service ────────────────────────────────────────

class TestSystemService:
    def test_status_headless(self):
        with patch.dict(os.environ, {"ORCH_HEADLESS": "true"}):
            from tools.gimo_server.services.system_service import SystemService
            assert SystemService.get_status() == "RUNNING (MOCK)"

    def test_restart_success(self):
        with patch("subprocess.run") as mock_run:
            from tools.gimo_server.services.system_service import SystemService
            assert SystemService.restart() is True
            assert mock_run.call_count == 2
@pytest.mark.asyncio
async def test_evals_service_regression_passes_all_cases():
    workflow = WorkflowGraph(id="wf_eval_ok", nodes=[WorkflowNode(id="A", type="transform", config={})], edges=[])
    dataset = EvalDataset(workflow_id="wf_eval_ok", name="ts", cases=[EvalGoldenCase(case_id="c1", input_state={}, expected_state={"result": "ok"}, threshold=1.0)])
    with patch("tools.gimo_server.services.evals_service.GraphEngine.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock()
        mock_exec.return_value.data = {"result": "ok"}
        report = await EvalsService.run_regression(workflow=workflow, dataset=dataset, judge=EvalJudgeConfig(enabled=False), gate=EvalGateConfig(min_pass_rate=1.0, min_avg_score=1.0))
        assert math.isclose(report.pass_rate, 1.0)
        assert report.gate_passed is True

@pytest.mark.asyncio
async def test_evals_service_regression_fails_gate_on_mismatch():
    workflow = WorkflowGraph(id="wf_f", nodes=[WorkflowNode(id="A", type="transform", config={})], edges=[])
    dataset = EvalDataset(workflow_id="wf_f", name="ts", cases=[EvalGoldenCase(case_id="c1", input_state={}, expected_state={"result": "exp"}, threshold=1.0)])
    with patch("tools.gimo_server.services.evals_service.GraphEngine.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock()
        mock_exec.return_value.data = {"result": "actual"}
        report = await EvalsService.run_regression(workflow=workflow, dataset=dataset, judge=EvalJudgeConfig(enabled=True, mode="heuristic", output_key="result"), gate=EvalGateConfig(min_pass_rate=1.0, min_avg_score=1.0))
        assert report.gate_passed is False

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


def test_ops_service_gics_bridge_seed_record_get():
    from tools.gimo_server.services.ops_service import OpsService

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


@pytest.mark.asyncio
async def test_provider_service_static_generate_records_outcome_success():
    fake_cfg = SimpleNamespace(
        active="p1",
        providers={
            "p1": SimpleNamespace(model="gpt-4o-mini", provider_type="openai", type="openai")
        },
    )
    fake_economy = SimpleNamespace(cache_enabled=False, cache_ttl_hours=24)

    class _Adapter:
        model = "gpt-4o-mini"

        async def generate(self, prompt, context):
            await asyncio.sleep(0)
            return {
                "content": "ok",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    with patch.object(ProviderService, "get_config", return_value=fake_cfg):
        with patch.object(ProviderService, "_build_adapter", return_value=_Adapter()):
            with patch("tools.gimo_server.services.ops_service.OpsService.get_config", return_value=SimpleNamespace(economy=fake_economy)):
                with patch("tools.gimo_server.services.ops_service.OpsService.record_model_outcome") as mock_record:
                    result = await ProviderService.static_generate("hola", {"task_type": "coding"})

    assert result["content"] == "ok"
    assert mock_record.call_count == 1
    kwargs = mock_record.call_args.kwargs
    assert kwargs["success"] is True
    assert kwargs["provider_type"] == "openai"
    assert kwargs["model_id"] == "gpt-4o-mini"
    assert kwargs["task_type"] == "coding"


@pytest.mark.asyncio
async def test_provider_service_static_generate_records_outcome_failure():
    fake_cfg = SimpleNamespace(
        active="p1",
        providers={
            "p1": SimpleNamespace(model="gpt-4o-mini", provider_type="openai", type="openai")
        },
    )
    fake_economy = SimpleNamespace(cache_enabled=False, cache_ttl_hours=24)

    class _Adapter:
        model = "gpt-4o-mini"

        async def generate(self, prompt, context):
            raise RuntimeError("boom")

    with patch.object(ProviderService, "get_config", return_value=fake_cfg):
        with patch.object(ProviderService, "_build_adapter", return_value=_Adapter()):
            with patch("tools.gimo_server.services.ops_service.OpsService.get_config", return_value=SimpleNamespace(economy=fake_economy)):
                with patch("tools.gimo_server.services.ops_service.OpsService.record_model_outcome") as mock_record:
                    with pytest.raises(RuntimeError):
                        await ProviderService.static_generate("hola", {"task_type": "coding"})

    assert mock_record.call_count == 1
    kwargs = mock_record.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["provider_type"] == "openai"
    assert kwargs["model_id"] == "gpt-4o-mini"
    assert kwargs["task_type"] == "coding"
