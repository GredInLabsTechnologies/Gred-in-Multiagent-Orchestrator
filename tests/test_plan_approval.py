"""Tests for POST /ops/threads/{id}/plan/respond — P2 plan approval endpoint."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from tools.gimo_server.services.conversation_service import ConversationService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


SAMPLE_PLAN = {
    "title": "Refactor auth module",
    "objective": "Improve security posture",
    "tasks": [
        {"id": "t1", "title": "Review code", "agent_rationale": "Need forensic analysis", "mood": "forensic"},
        {"id": "t2", "title": "Apply fixes", "agent_rationale": "Direct execution", "mood": "executor"},
    ],
}


def _create_thread_with_plan(test_client, valid_token, workspace_root, plan=None):
    """Create a thread via API, then patch its JSON to add a proposed plan."""
    resp = test_client.post(
        "/ops/threads",
        params={"workspace_root": workspace_root, "title": "Test Plan Thread"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert resp.status_code == 201
    thread_id = resp.json()["id"]

    # Patch the thread file directly to add proposed_plan and legacy mood hint
    thread_path = ConversationService.THREADS_DIR / f"{thread_id}.json"
    data = json.loads(thread_path.read_text(encoding="utf-8"))
    data["proposed_plan"] = plan or SAMPLE_PLAN
    data["mood"] = "dialoger"
    thread_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    return thread_id


class TestPlanApproval:
    def test_approve_transitions_to_executing_phase(self, test_client, valid_token, tmp_path):
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path))

        # CustomPlanService is imported lazily inside the handler, so we patch
        # the module-level class that the local import will resolve to.
        mock_plan = MagicMock()
        mock_plan.id = "plan_test123"

        with patch("tools.gimo_server.services.custom_plan_service.CustomPlanService") as mock_cps:
            mock_cps.create_plan_from_llm.return_value = mock_plan
            mock_cps.execute_plan = AsyncMock()

            resp = test_client.post(
                f"/ops/threads/{thread_id}/plan/respond",
                params={"action": "approve"},
                headers={"Authorization": f"Bearer {valid_token}"},
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "approved"
        assert data["workflow_phase"] == "executing"
        assert "plan_id" in data
        approved_plan = mock_cps.create_plan_from_llm.call_args.kwargs["plan_data"]
        assert "task_descriptor" in approved_plan["tasks"][0]
        assert "task_fingerprint" in approved_plan["tasks"][0]

        # Verify thread state updated
        thread = ConversationService.get_thread(thread_id)
        assert thread.workflow_phase == "executing"
        assert thread.metadata.get("plan_approved") is True
        assert "task_descriptor" in thread.proposed_plan["tasks"][0]
        assert "task_fingerprint" in thread.proposed_plan["tasks"][0]

    def test_reject_transitions_to_planning_phase(self, test_client, valid_token, tmp_path):
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path))

        resp = test_client.post(
            f"/ops/threads/{thread_id}/plan/respond",
            params={"action": "reject", "feedback": "Too many steps"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["workflow_phase"] == "planning"

        thread = ConversationService.get_thread(thread_id)
        assert thread.workflow_phase == "planning"
        assert thread.proposed_plan is None

    def test_approve_failure_does_not_mark_thread_as_approved(self, test_client, valid_token, tmp_path):
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path))

        with patch("tools.gimo_server.services.custom_plan_service.CustomPlanService") as mock_cps:
            mock_cps.create_plan_from_llm.side_effect = RuntimeError("boom")

            resp = test_client.post(
                f"/ops/threads/{thread_id}/plan/respond",
                params={"action": "approve"},
                headers={"Authorization": f"Bearer {valid_token}"},
            )

        assert resp.status_code == 500
        thread = ConversationService.get_thread(thread_id)
        assert thread is not None
        assert thread.workflow_phase == "intake"
        assert thread.metadata.get("plan_approved") is None
        assert thread.proposed_plan["title"] == SAMPLE_PLAN["title"]
        assert "task_descriptor" in thread.proposed_plan["tasks"][0]
        assert "task_fingerprint" in thread.proposed_plan["tasks"][0]

    def test_modify_updates_plan(self, test_client, valid_token, tmp_path):
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path))
        modified = {"title": "Smaller plan", "objective": "Quick fix", "tasks": [
            {"id": "t1", "title": "Fix bug", "agent_rationale": "Direct fix", "mood": "executor"},
        ]}

        resp = test_client.post(
            f"/ops/threads/{thread_id}/plan/respond",
            params={"action": "modify"},
            headers={"Authorization": f"Bearer {valid_token}"},
            json=modified,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "modified"
        assert "task_descriptor" in data["modified_plan"]["tasks"][0]
        assert "task_fingerprint" in data["modified_plan"]["tasks"][0]

        thread = ConversationService.get_thread(thread_id)
        assert thread.proposed_plan["title"] == "Smaller plan"
        assert "task_descriptor" in thread.proposed_plan["tasks"][0]
        assert "task_fingerprint" in thread.proposed_plan["tasks"][0]

    def test_approve_preserves_existing_canonical_plan(self, test_client, valid_token, tmp_path):
        canonical_plan = TaskDescriptorService.canonicalize_plan_data(SAMPLE_PLAN)
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path), plan=canonical_plan)

        mock_plan = MagicMock()
        mock_plan.id = "plan_test123"

        with patch("tools.gimo_server.services.custom_plan_service.CustomPlanService") as mock_cps:
            mock_cps.create_plan_from_llm.return_value = mock_plan
            mock_cps.execute_plan = AsyncMock()

            resp = test_client.post(
                f"/ops/threads/{thread_id}/plan/respond",
                params={"action": "approve"},
                headers={"Authorization": f"Bearer {valid_token}"},
            )

        assert resp.status_code == 200
        approved_plan = mock_cps.create_plan_from_llm.call_args.kwargs["plan_data"]
        assert approved_plan == canonical_plan

    def test_404_thread_not_found(self, test_client, valid_token):
        resp = test_client.post(
            "/ops/threads/nonexistent_thread/plan/respond",
            params={"action": "approve"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 404

    def test_404_no_proposed_plan(self, test_client, valid_token, tmp_path):
        # Create thread via API (no plan)
        create_resp = test_client.post(
            "/ops/threads",
            params={"workspace_root": str(tmp_path), "title": "No Plan Thread"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        thread_id = create_resp.json()["id"]

        resp = test_client.post(
            f"/ops/threads/{thread_id}/plan/respond",
            params={"action": "approve"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 404
        assert "plan" in resp.json()["detail"].lower()

    def test_invalid_action_returns_400(self, test_client, valid_token, tmp_path):
        thread_id = _create_thread_with_plan(test_client, valid_token, str(tmp_path))

        resp = test_client.post(
            f"/ops/threads/{thread_id}/plan/respond",
            params={"action": "invalid_action"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 400
