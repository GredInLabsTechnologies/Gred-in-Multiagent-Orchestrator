"""Unit tests for tools.gimo_server.services.run_worker.RunWorker.

Tests cover lifecycle (start/stop/notify), tick dispatch logic,
concurrency limits, active-status detection, target-path extraction,
and execute_run error handling.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(run_id: str, status: str = "pending", parent_run_id=None):
    return SimpleNamespace(
        id=run_id,
        status=status,
        parent_run_id=parent_run_id,
        approved_id=None,
        child_context=None,
        awaiting_count=0,
    )


def _make_config(max_concurrent=3):
    return SimpleNamespace(max_concurrent_runs=max_concurrent)


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestRunWorkerLifecycle:
    """Tests for start / stop / notify methods."""

    @pytest.mark.asyncio
    async def test_start_creates_task_and_sets_running(self):
        from tools.gimo_server.services.run_worker import RunWorker

        worker = RunWorker()
        assert worker._running is False
        assert worker._task is None

        await worker.start()
        assert worker._running is True
        assert worker._task is not None
        assert not worker._task.done()

        # Cleanup
        await worker.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task_and_clears_running(self):
        from tools.gimo_server.services.run_worker import RunWorker

        worker = RunWorker()
        await worker.start()
        assert worker._running is True

        await worker.stop()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_notify_sets_wake_event(self):
        from tools.gimo_server.services.run_worker import RunWorker

        worker = RunWorker()
        assert not worker._wake_event.is_set()
        worker.notify()
        assert worker._wake_event.is_set()


# ---------------------------------------------------------------------------
# _is_still_active
# ---------------------------------------------------------------------------

class TestIsStillActive:
    """Tests for _is_still_active status classification."""

    def _build_worker(self):
        from tools.gimo_server.services.run_worker import RunWorker
        return RunWorker()

    @patch("tools.gimo_server.services.run_worker.OpsService")
    def test_active_statuses_return_true(self, mock_ops):
        worker = self._build_worker()
        for status in ("pending", "running", "awaiting_subagents", "awaiting_review"):
            mock_ops.get_run.return_value = _make_run("r1", status=status)
            assert worker._is_still_active("r1") is True

    @patch("tools.gimo_server.services.run_worker.OpsService")
    def test_terminal_statuses_return_false(self, mock_ops):
        worker = self._build_worker()
        for status in ("done", "error", "cancelled"):
            mock_ops.get_run.return_value = _make_run("r1", status=status)
            assert worker._is_still_active("r1") is False

    @patch("tools.gimo_server.services.run_worker.OpsService")
    def test_missing_run_returns_false(self, mock_ops):
        worker = self._build_worker()
        mock_ops.get_run.return_value = None
        assert worker._is_still_active("nonexistent") is False


# ---------------------------------------------------------------------------
# _extract_target_path (static method — no mocks needed)
# ---------------------------------------------------------------------------

class TestExtractTargetPath:
    """Tests for RunWorker._extract_target_path with various input patterns."""

    def _extract(self, text: str):
        from tools.gimo_server.services.run_worker import RunWorker
        return RunWorker._extract_target_path(text)

    def test_explicit_target_file_directive(self):
        assert self._extract("Please edit TARGET_FILE: src/main.py now") == "src/main.py"

    def test_windows_absolute_path(self):
        result = self._extract("modify C:/Users/dev/project/app.py")
        assert result == "C:/Users/dev/project/app.py"

    def test_relative_path_with_directory(self):
        result = self._extract("update docs/DISEÑO_CALCULADORA.md content")
        assert result == "docs/DISEÑO_CALCULADORA.md"

    def test_quoted_filename(self):
        result = self._extract("create a file called 'report.txt'")
        assert result == "report.txt"

    def test_bare_filename_after_keyword(self):
        result = self._extract("create setup.py with the config")
        assert result == "setup.py"

    def test_no_match_returns_none(self):
        assert self._extract("just a plain sentence with no files") is None


# ---------------------------------------------------------------------------
# _tick dispatch
# ---------------------------------------------------------------------------

class TestTick:
    """Tests for _tick dispatch and concurrency logic."""

    @pytest.mark.asyncio
    @patch("tools.gimo_server.services.run_worker.OpsService")
    async def test_tick_dispatches_pending_runs(self, mock_ops):
        from tools.gimo_server.services.run_worker import RunWorker

        mock_ops.get_config.return_value = _make_config(max_concurrent=3)
        mock_ops.list_pending_runs.return_value = [_make_run("r1"), _make_run("r2")]
        mock_ops.get_run.return_value = None  # for _is_still_active cleanup

        worker = RunWorker()

        # Patch _execute_run to avoid real execution
        with patch.object(worker, "_execute_run", new_callable=AsyncMock) as mock_exec:
            # Make ExecutionAuthority.get() raise RuntimeError so ResourceGovernor is skipped
            authority_module = MagicMock()
            authority_module.ExecutionAuthority.get.side_effect = RuntimeError("not initialized")
            with patch.dict("sys.modules", {"tools.gimo_server.services.authority": authority_module}):
                await worker._tick()

        assert "r1" in worker._running_ids and "r2" in worker._running_ids

    @pytest.mark.asyncio
    @patch("tools.gimo_server.services.run_worker.OpsService")
    async def test_tick_respects_max_concurrent(self, mock_ops):
        from tools.gimo_server.services.run_worker import RunWorker

        mock_ops.get_config.return_value = _make_config(max_concurrent=1)
        mock_ops.list_pending_runs.return_value = [_make_run("r1"), _make_run("r2")]
        mock_ops.get_run.return_value = _make_run("r0", status="running")  # active

        worker = RunWorker()
        worker._running_ids = {"r0"}

        # With 1 slot and 1 active, available_slots = 0 => no dispatch
        await worker._tick()

        # r1 and r2 should NOT have been added (only r0 remains or is cleaned)
        assert "r1" not in worker._running_ids
        assert "r2" not in worker._running_ids


# ---------------------------------------------------------------------------
# _execute_run
# ---------------------------------------------------------------------------

class TestExecuteRun:
    """Tests for _execute_run delegation and error handling."""

    @pytest.mark.asyncio
    @patch("tools.gimo_server.services.run_worker.OpsService")
    async def test_execute_run_delegates_to_engine_service(self, mock_ops):
        from tools.gimo_server.services.run_worker import RunWorker

        mock_ops.get_run.return_value = _make_run("r1", status="done")

        worker = RunWorker()
        worker._running_ids.add("r1")

        with patch("tools.gimo_server.services.engine_service.EngineService.execute_run", new_callable=AsyncMock) as mock_engine:
            await worker._execute_run("r1")
            mock_engine.assert_awaited_once_with("r1")

        # After completion, running_ids should be cleaned up
        assert "r1" not in worker._running_ids

    @pytest.mark.asyncio
    @patch("tools.gimo_server.services.run_worker.OpsService")
    async def test_execute_run_handles_engine_exception(self, mock_ops):
        from tools.gimo_server.services.run_worker import RunWorker

        mock_ops.get_run.return_value = _make_run("r1", status="error")

        worker = RunWorker()
        worker._running_ids.add("r1")

        with patch("tools.gimo_server.services.engine_service.EngineService.execute_run", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            # Should not raise
            await worker._execute_run("r1")

        mock_ops.update_run_status.assert_called_with("r1", "error", msg="Internal engine error")
        assert "r1" not in worker._running_ids


@pytest.mark.asyncio
@patch("tools.gimo_server.services.run_worker.OpsService")
async def test_critic_gate_skips_mature_high_quality_outputs(mock_ops):
    from tools.gimo_server.services.run_worker import RunWorker

    class FakeGics:
        def __init__(self):
            self.writes = []

        def get(self, _key):
            return {"fields": {"samples": 20, "success_rate": 0.95, "successes": 19, "critic_calls": 4, "critic_skips": 3}}

        def put(self, key, value):
            self.writes.append((key, value))

    mock_ops._gics = FakeGics()

    worker = RunWorker()

    with patch("tools.gimo_server.services.run_worker.CriticService.evaluate", new_callable=AsyncMock) as mock_critic:
        approved, output, raw = await worker._critic_with_retry(
            run_id="r1",
            output_text="Concrete execution summary with no errors.",
            base_prompt="Do the thing",
            intent_effective="EXECUTE",
            path_scope=[],
            requested_model="test-model",
            initial_raw={
                "content": "Concrete execution summary with no errors.",
                "usage": {"completion_tokens": 42},
                "final_model_used": "test-model",
            },
        )

    assert approved is True
    assert output == "Concrete execution summary with no errors."
    assert raw["content"] == "Concrete execution summary with no errors."
    mock_critic.assert_not_awaited()
    assert mock_ops._gics.writes
    _, persisted = mock_ops._gics.writes[-1]
    assert persisted["critic_skips"] == 4
    assert "avg_output_tokens" in persisted
    assert persisted["avg_output_tokens"] > 0
