from __future__ import annotations

from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
from tools.gimo_server.services.task_fingerprint_service import TaskFingerprintService


def test_normalize_plan_data_preserves_conversational_shape_fields():
    plan = {
        "title": "Ship feature",
        "objective": "Implement change",
        "tasks": [
            {
                "id": "t1",
                "title": "Investigate API",
                "description": "Read docs and understand the endpoint",
                "depends_on": ["t0"],
                "agent_mood": "forensic",
                "model": "gpt-4o",
                "agent_rationale": "Need careful analysis",
            }
        ],
    }

    normalized = TaskDescriptorService.normalize_plan_data(plan)
    task = normalized["tasks"][0]

    assert task["depends_on"] == ["t0"]
    assert task["legacy_mood"] == "forensic"
    assert task["requested_model"] == "gpt-4o"
    assert task["agent_rationale"] == "Need careful analysis"
    assert task["source_shape"] == "conversational_plan"


def test_descriptor_and_fingerprint_match_across_structured_and_conversational_shapes():
    structured = {
        "id": "t1",
        "title": "Investigate auth flow",
        "description": "Investigate auth behavior and gather evidence",
        "depends": ["t0"],
        "agent_assignee": {
            "role": "researcher",
            "model": "gpt-4o",
            "system_prompt": "Be thorough.",
        },
    }
    conversational = {
        "id": "t1",
        "title": "Investigate auth flow",
        "description": "Investigate auth behavior and gather evidence",
        "depends_on": ["t0"],
        "agent_mood": "forensic",
        "model": "gpt-4o",
        "agent_rationale": "Need careful analysis",
    }

    structured_descriptor = TaskDescriptorService.descriptor_from_task(structured)
    conversational_descriptor = TaskDescriptorService.descriptor_from_task(conversational)

    assert structured_descriptor.task_semantic == conversational_descriptor.task_semantic == "research"
    assert structured_descriptor.mutation_mode == conversational_descriptor.mutation_mode == "none"
    assert (
        TaskFingerprintService.fingerprint_for_descriptor(structured_descriptor)
        == TaskFingerprintService.fingerprint_for_descriptor(conversational_descriptor)
    )
