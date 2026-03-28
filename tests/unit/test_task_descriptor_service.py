from __future__ import annotations

from tools.gimo_server.models.agent_routing import TaskDescriptor
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
    assert task["agent_preset"] == "researcher"
    assert task["legacy_mood"] == "forensic"
    assert task["requested_model"] == "gpt-4o"
    assert task["agent_rationale"] == "Need careful analysis"
    assert task["source_shape"] == "conversational_plan"


def test_canonicalize_plan_data_adds_descriptor_and_fingerprint_to_conversational_tasks():
    plan = {
        "title": "Ship feature",
        "objective": "Implement change",
        "context": {"surface": "chatgpt_app", "workspace_mode": "ephemeral", "budget_mode": "tight"},
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

    canonical = TaskDescriptorService.canonicalize_plan_data(plan)
    task = canonical["tasks"][0]
    descriptor = TaskDescriptor.model_validate(task["task_descriptor"])

    assert canonical["context"] == {"surface": "chatgpt_app", "workspace_mode": "ephemeral", "budget_mode": "tight"}
    assert task["depends_on"] == ["t0"]
    assert task["agent_preset"] == "researcher"
    assert task["legacy_mood"] == "forensic"
    assert task["requested_model"] == "gpt-4o"
    assert task["agent_rationale"] == "Need careful analysis"
    assert task["source_shape"] == "conversational_plan"
    assert descriptor.task_id == "t1"
    assert descriptor.title == "Investigate API"
    assert task["task_fingerprint"] == TaskFingerprintService.fingerprint_for_descriptor(descriptor)


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

    structured_task = TaskDescriptorService.canonicalize_task(structured)
    conversational_task = TaskDescriptorService.canonicalize_task(conversational)
    structured_descriptor = TaskDescriptor.model_validate(structured_task["task_descriptor"])
    conversational_descriptor = TaskDescriptor.model_validate(conversational_task["task_descriptor"])

    assert structured_descriptor.task_semantic == conversational_descriptor.task_semantic == "research"
    assert structured_descriptor.mutation_mode == conversational_descriptor.mutation_mode == "none"
    assert conversational_task["agent_preset"] == "researcher"
    assert structured_task["task_fingerprint"] == conversational_task["task_fingerprint"]


def test_canonicalize_task_is_idempotent_for_canonical_shape():
    raw_task = {
        "id": "t1",
        "title": "Investigate auth flow",
        "description": "Investigate auth behavior and gather evidence",
        "depends_on": ["t0"],
        "agent_mood": "forensic",
        "model": "gpt-4o",
        "agent_rationale": "Need careful analysis",
    }

    canonical_task = TaskDescriptorService.canonicalize_task(raw_task)
    rewritten_task = TaskDescriptorService.canonicalize_task(canonical_task)

    assert rewritten_task == canonical_task


def test_canonicalize_plan_content_serializes_write_new_shape():
    plan = {
        "title": "Ship feature",
        "objective": "Implement change",
        "context": {"surface": "operator", "workspace_mode": "source_repo"},
        "tasks": [
            {
                "id": "t1",
                "title": "Investigate API",
                "description": "Read docs and understand the endpoint",
                "depends_on": ["t0"],
                "agent_mood": "forensic",
                "model": "gpt-4o",
            }
        ],
    }

    content = TaskDescriptorService.canonicalize_plan_content(plan)

    assert '"task_descriptor"' in content
    assert '"task_fingerprint"' in content
    assert '"context"' in content


def test_maybe_canonicalize_plan_content_leaves_non_plan_json_unchanged():
    content = '{"message": "hello"}'

    assert TaskDescriptorService.maybe_canonicalize_plan_content(content) == content
