"""Surface authority regression guards.

These tests enforce the invariant declared in AGENTS.md §Architectural Rules —
"Backend authority first":

    For lifecycle, status, approvals, runs, threads, notices, merge state, and
    policy:
      - prefer authoritative backend services and contracts
      - avoid client-side inferred truth
      - avoid duplicated status computation across surfaces

And the parity closure table in docs/CLIENT_SURFACES.md.

Regression guard for audit findings:
  F1 — merge gate policy bypass (see test_merge_gate_fail_closed.py)
  F2 — legacy /ui/status computing status locally
  F3 — TypeScript contract drift (see codegen:check)
  F6 — NoticePolicyService disconnected from NotificationService

When these tests start failing, someone has reintroduced surface-local state
inference. Fix the producer, not the test.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_UI_ROUTER = _REPO_ROOT / "tools" / "gimo_server" / "routers" / "legacy_ui_router.py"
_OPERATOR_STATUS = _REPO_ROOT / "tools" / "gimo_server" / "services" / "operator_status_service.py"


class TestUiStatusDelegatesToOperatorStatusService:
    """F2 fix: /ui/status must delegate to OperatorStatusService, not compute locally.

    The legacy router is currently unmounted (see file docstring). These tests
    are source-based so they survive the unmounted state: if anyone re-mounts
    the router, the canonical delegation pattern is already in place and the
    tests stay meaningful without requiring runtime imports.
    """

    def test_handler_delegates_to_ui_status_snapshot(self):
        """Body of get_ui_status must call OperatorStatusService.ui_status_snapshot."""
        source = _LEGACY_UI_ROUTER.read_text(encoding="utf-8")
        start = source.find("def get_ui_status(")
        assert start > 0, "get_ui_status handler not found"
        end = source.find("@router", start + 1)
        assert end > start, "could not find end of get_ui_status handler"
        body = source[start:end]

        assert "OperatorStatusService" in body, (
            "/ui/status handler must reference OperatorStatusService — "
            "it is the canonical status producer."
        )
        assert "ui_status_snapshot" in body, (
            "/ui/status handler must call OperatorStatusService.ui_status_snapshot — "
            "never recompute allowlist/audit/service_status locally."
        )

    def test_legacy_handler_does_not_compute_allowlist_locally(self):
        """Regression guard: the handler body must not call get_allowed_paths or
        FileService directly. Those calls belong inside OperatorStatusService.

        If you're adding a new field to UiStatusResponse, extend
        OperatorStatusService.ui_status_snapshot — don't reintroduce local
        computation in the router.
        """
        source = _LEGACY_UI_ROUTER.read_text(encoding="utf-8")
        # Locate the get_ui_status handler body (until the next @router decorator).
        start = source.find("def get_ui_status(")
        assert start > 0, "get_ui_status handler not found"
        end = source.find("@router", start + 1)
        assert end > start, "could not find end of get_ui_status handler"
        body = source[start:end]

        forbidden_locals = ["get_allowed_paths(", "FileService.tail_audit_lines"]
        for call in forbidden_locals:
            assert call not in body, (
                f"/ui/status handler computes {call!r} locally — this duplicates "
                f"OperatorStatusService authority. Delegate instead."
            )


class TestOperatorStatusReconnectsNotices:
    """F6 fix: NoticePolicyService notices must flow through NotificationService."""

    def test_status_snapshot_broadcasts_new_notice(self):
        """When a new notice appears, OperatorStatusService publishes it via NotificationService."""
        from tools.gimo_server.services.operator_status_service import OperatorStatusService

        # Reset cache so this test is deterministic regardless of previous state
        OperatorStatusService._last_broadcast_notice_codes = set()

        published: list[tuple[str, dict]] = []

        async def _fake_publish(event_type, payload):
            published.append((event_type, payload))

        new_alert = {"code": "stream_down", "level": "error", "message": "Stream is down"}

        with patch(
            "tools.gimo_server.services.notification_service.NotificationService.publish",
            side_effect=_fake_publish,
        ), patch("asyncio.get_running_loop") as mock_loop:
            fake_loop = MagicMock()
            captured_coros = []

            def _create_task(coro):
                captured_coros.append(coro)
                return MagicMock()

            fake_loop.create_task.side_effect = _create_task
            mock_loop.return_value = fake_loop

            OperatorStatusService._broadcast_new_notices([new_alert])

            # Run the captured coroutines to check they publish the notice
            import asyncio
            for coro in captured_coros:
                asyncio.run(coro)

        assert any(
            evt == "notice_appeared" and payload.get("code") == "stream_down"
            for evt, payload in published
        ), f"Expected notice_appeared publish for stream_down, got {published}"

    def test_status_snapshot_does_not_republish_existing_notice(self):
        """A notice that persists across evaluations fires exactly once until cleared."""
        from tools.gimo_server.services.operator_status_service import OperatorStatusService

        # Pre-populate the cache as if stream_down was already broadcast
        OperatorStatusService._last_broadcast_notice_codes = {"stream_down"}

        persistent_alert = {"code": "stream_down", "level": "error", "message": "Stream is down"}

        with patch("asyncio.get_running_loop") as mock_loop:
            fake_loop = MagicMock()
            mock_loop.return_value = fake_loop
            OperatorStatusService._broadcast_new_notices([persistent_alert])

        # No new task created because stream_down was already in _last_broadcast_notice_codes
        fake_loop.create_task.assert_not_called()

    def test_status_snapshot_refires_after_clear(self):
        """When a notice clears and reappears, it fires again."""
        from tools.gimo_server.services.operator_status_service import OperatorStatusService

        # Previously had stream_down; now the evaluation returns nothing
        OperatorStatusService._last_broadcast_notice_codes = {"stream_down"}

        with patch("asyncio.get_running_loop") as mock_loop:
            fake_loop = MagicMock()
            mock_loop.return_value = fake_loop
            OperatorStatusService._broadcast_new_notices([])

        # Cache drops stream_down
        assert "stream_down" not in OperatorStatusService._last_broadcast_notice_codes

        # Now stream_down reappears — should fire
        reappearing = {"code": "stream_down", "level": "error", "message": "Stream is down"}
        with patch("asyncio.get_running_loop") as mock_loop:
            fake_loop = MagicMock()
            fake_loop.create_task.return_value = MagicMock()
            mock_loop.return_value = fake_loop
            OperatorStatusService._broadcast_new_notices([reappearing])

        fake_loop.create_task.assert_called_once()


class TestContractCoverage:
    """F3 regression guard at the Python level: Pydantic models must cover all the
    statuses that the backend actually writes. If a state transition emits a status
    not declared in OpsRunStatus, the TypeScript codegen will be blind to it and
    any polling/rendering logic will fall back silently.
    """

    def test_all_merge_gate_status_transitions_covered_by_ops_run_status(self):
        """Every update_run_status call in merge_gate_service must use a declared status."""
        import re
        from tools.gimo_server.models.core import OpsRunStatus
        import typing

        # Extract the literal values from OpsRunStatus (typing.Literal[...])
        canonical = set(typing.get_args(OpsRunStatus))

        merge_gate_src = (_REPO_ROOT / "tools" / "gimo_server" / "services" / "merge_gate_service.py").read_text(
            encoding="utf-8"
        )
        # Find all literal status strings passed as the 2nd arg to update_run_status.
        # Pattern: update_run_status(run_id, "STATUS_NAME", ...)
        pattern = re.compile(r'update_run_status\([^,]+,\s*"([A-Za-z_]+)"')
        used_statuses = set(pattern.findall(merge_gate_src))

        unknown = used_statuses - canonical
        assert not unknown, (
            f"merge_gate_service emits status values not declared in OpsRunStatus: {unknown}. "
            f"Add them to models/core.py OpsRunStatus — otherwise the UI codegen "
            f"won't know about them (audit F3 regression risk)."
        )
