from __future__ import annotations

import json

from tools.gimo_server.ops_models import OpsApproved
from tools.gimo_server.services.ops import OpsService
from tools.gimo_server.services.plan_graph_builder import build_graph_from_ops_plan
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


def _setup_ops_dirs(tmp_path):
    OpsService.OPS_DIR = tmp_path / "ops"
    OpsService.DRAFTS_DIR = OpsService.OPS_DIR / "drafts"
    OpsService.APPROVED_DIR = OpsService.OPS_DIR / "approved"
    OpsService.RUNS_DIR = OpsService.OPS_DIR / "runs"
    OpsService.LOCKS_DIR = OpsService.OPS_DIR / "locks"
    OpsService.CONFIG_FILE = OpsService.OPS_DIR / "config.json"
    OpsService.LOCK_FILE = OpsService.OPS_DIR / ".ops.lock"
    OpsService.ensure_dirs()


def test_build_graph_from_approved_supports_canonical_plan_content(tmp_path):
    _setup_ops_dirs(tmp_path)
    canonical_plan = TaskDescriptorService.canonicalize_plan_data(
        {
            "title": "Ship feature",
            "objective": "Implement change",
            "tasks": [
                {
                    "id": "t1",
                    "title": "Investigate API",
                    "description": "Read docs and understand the endpoint",
                    "depends_on": [],
                    "agent_mood": "forensic",
                    "model": "gpt-4o",
                },
                {
                    "id": "t2",
                    "title": "Apply fix",
                    "description": "Patch the API client",
                    "depends_on": ["t1"],
                    "agent_mood": "executor",
                    "model": "gpt-4o",
                },
            ],
        }
    )
    approved = OpsApproved(
        id="a_1",
        draft_id="d_1",
        prompt="p",
        content=json.dumps(canonical_plan, indent=2),
    )
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")

    nodes, edges = build_graph_from_ops_plan(approved)

    assert len(nodes) == 2
    assert nodes[0]["data"]["task_fingerprint"] == canonical_plan["tasks"][0]["task_fingerprint"]
    assert edges[0]["source"] == "t1"
    assert edges[0]["target"] == "t2"
