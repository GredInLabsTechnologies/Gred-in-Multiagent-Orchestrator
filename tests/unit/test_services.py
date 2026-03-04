import pytest
import asyncio
import math
import os
from unittest.mock import MagicMock, AsyncMock, patch
from tools.gimo_server.ops_models import WorkflowNode, TrustEvent, EvalDataset, EvalGateConfig, EvalGoldenCase, EvalJudgeConfig, WorkflowGraph
from tools.gimo_server.services.model_router_service import ModelRouterService, RoutingDecision
from tools.gimo_server.services.provider_service import ProviderService
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

# ── Model Router & Budget ─────────────────────────────────

@pytest.mark.asyncio
class TestModelRouter:
    async def test_policy_routing(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "security_review"})
        decision = await router.choose_model(node, state={})
        assert decision.model != "unknown"
        assert decision.tier >= 1

    async def test_budget_degradation(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "code_generation"})
        state = {"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 9.5}}
        decision = await router.choose_model(node, state=state)
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
