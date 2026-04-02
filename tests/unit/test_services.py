import pytest
import math
import os
from unittest.mock import MagicMock, AsyncMock, patch
from tools.gimo_server.ops_models import WorkflowNode, EvalDataset, EvalGateConfig, EvalGoldenCase, EvalJudgeConfig, WorkflowGraph
from tools.gimo_server.services.quality_service import QualityService
from tools.gimo_server.services.llm_cache import NormalizedLLMCache
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.evals_service import EvalsService

# ── Shared Stubs (imported by test_institutional_memory.py) ──


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

# ── Evals Service ─────────────────────────────────────────


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
