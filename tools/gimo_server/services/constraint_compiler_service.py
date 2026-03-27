from __future__ import annotations

from ..models.agent_routing import TaskConstraints, TaskDescriptor


class ConstraintCompilerService:
    @classmethod
    def compile_for_descriptor(cls, descriptor: TaskDescriptor) -> TaskConstraints:
        if descriptor.task_semantic == "planning":
            return TaskConstraints(
                allowed_policies=["propose_only", "read_only"],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
            )
        if descriptor.task_semantic == "research":
            return TaskConstraints(
                allowed_policies=["docs_research", "read_only"],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
            )
        if descriptor.task_semantic == "security":
            return TaskConstraints(
                allowed_policies=["security_audit", "read_only"],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
            )
        if descriptor.task_semantic == "review":
            return TaskConstraints(
                allowed_policies=["read_only", "security_audit"],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
            )
        if descriptor.task_semantic == "approval":
            return TaskConstraints(
                allowed_policies=["propose_only"],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=True,
            )
        return TaskConstraints(
            allowed_policies=["workspace_safe", "workspace_experiment"],
            allowed_binding_modes=["plan_time"],
            requires_human_approval=False,
        )
