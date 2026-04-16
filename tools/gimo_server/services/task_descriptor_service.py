from __future__ import annotations

import json
from typing import Any, Dict, List

from ..models.agent_routing import TaskDescriptor
from .agent_catalog_service import AgentCatalogService
from .task_fingerprint_service import TaskFingerprintService


class TaskDescriptorService:
    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def coerce_plan_data(plan_data: Any) -> Dict[str, Any]:
        if hasattr(plan_data, "model_dump"):
            candidate = plan_data.model_dump(mode="json")
        elif isinstance(plan_data, str):
            candidate = json.loads(plan_data)
        elif isinstance(plan_data, dict):
            candidate = dict(plan_data)
        else:
            raise ValueError("Plan data must be a dictionary or JSON string")

        if not isinstance(candidate, dict):
            raise ValueError("Plan data must deserialize to a dictionary")
        return candidate

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @classmethod
    def normalize_task(cls, task: Dict[str, Any]) -> Dict[str, Any]:
        agent = task.get("agent_assignee") or {}
        depends_on = cls._string_list(task.get("depends_on") or task.get("depends"))
        raw_legacy_mood = task.get("legacy_mood") or task.get("agent_mood")
        raw_mood = task.get("mood") or raw_legacy_mood or agent.get("mood")
        requested_model = task.get("requested_model") or task.get("model") or agent.get("model") or "auto"
        requested_provider = task.get("requested_provider") or task.get("provider") or agent.get("provider") or "auto"
        role_definition = task.get("role_definition") or agent.get("system_prompt") or ""
        requested_role = task.get("requested_role") or task.get("role") or agent.get("role") or task.get("node_type") or "worker"
        agent_preset = str(task.get("agent_preset") or "").strip() or None
        canonical_mood = None
        if raw_mood:
            try:
                canonical_mood = AgentCatalogService.get_mood(str(raw_mood).strip()).name
            except KeyError:
                canonical_mood = None
        if not agent_preset and raw_mood:
            try:
                agent_preset = AgentCatalogService.resolve_preset_name(legacy_mood=str(raw_mood).strip())
            except KeyError:
                agent_preset = None
        return {
            "id": str(task.get("id") or "").strip(),
            "title": str(task.get("title") or "").strip(),
            "description": str(task.get("description") or "").strip(),
            "depends_on": depends_on,
            "requested_role": str(requested_role or "worker").strip(),
            "requested_model": str(requested_model or "auto").strip(),
            "requested_provider": str(requested_provider or "auto").strip(),
            "role_definition": str(role_definition).strip(),
            "mood": canonical_mood,
            "legacy_mood": str(raw_legacy_mood).strip() if raw_legacy_mood else None,
            "agent_preset": agent_preset,
            "agent_rationale": task.get("routing_rationale") or task.get("agent_rationale") or "",
            "path_scope": cls._string_list(task.get("path_scope") or task.get("paths")),
            "scope": str(task.get("scope") or "").strip(),
            "source_shape": cls.detect_source_shape(task),
        }

    @staticmethod
    def detect_source_shape(task: Dict[str, Any]) -> str:
        explicit_source_shape = str(task.get("source_shape") or "").strip()
        if explicit_source_shape in {"structured_plan", "conversational_plan", "manual", "legacy", "unknown"}:
            return explicit_source_shape
        if task.get("agent_assignee"):
            return "structured_plan"
        if task.get("agent_mood") is not None or task.get("legacy_mood") is not None or task.get("depends_on") is not None:
            return "conversational_plan"
        if task.get("mood") is not None and not task.get("agent_preset"):
            return "legacy"
        return "unknown"

    @classmethod
    def normalize_plan_data(cls, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        tasks = [cls.normalize_task(task) for task in (plan_data.get("tasks") or [])]
        return {
            "title": str(plan_data.get("title") or "").strip(),
            "objective": str(plan_data.get("objective") or "").strip(),
            "context": cls._dict(plan_data.get("context")),
            "tasks": tasks,
        }

    @classmethod
    def canonicalize_task(cls, task: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task, dict):
            raise ValueError("Task must be a dictionary")

        normalized = cls.normalize_task(task)
        descriptor = cls.descriptor_from_task(task)
        return {
            **normalized,
            "task_descriptor": descriptor.model_dump(mode="json"),
            "task_fingerprint": TaskFingerprintService.fingerprint_for_descriptor(descriptor),
        }

    @classmethod
    def canonicalize_plan_data(cls, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        plan_data = cls.coerce_plan_data(plan_data)
        tasks = plan_data.get("tasks") or []
        if not isinstance(tasks, list):
            raise ValueError("Plan tasks must be a list")
        return {
            "title": str(plan_data.get("title") or "").strip(),
            "objective": str(plan_data.get("objective") or "").strip(),
            "context": cls._dict(plan_data.get("context")),
            "tasks": [cls.canonicalize_task(task) for task in tasks],
        }

    @classmethod
    def canonicalize_plan_content(cls, plan_data: Any, *, indent: int = 2) -> str:
        return json.dumps(cls.canonicalize_plan_data(plan_data), indent=indent)

    @classmethod
    def maybe_canonicalize_plan_content(
        cls,
        content: str | None,
        *,
        indent: int = 2,
    ) -> str | None:
        if not isinstance(content, str) or not content.strip():
            return content
        try:
            plan_data = cls.coerce_plan_data(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            return content
        if "tasks" not in plan_data:
            return content
        return cls.canonicalize_plan_content(plan_data, indent=indent)

    # BUGS_LATENTES §H2 — tool name canonical vocabulary.
    # El campo TaskDescriptor.required_tools era dead (siempre vacío). Ahora se
    # infiere del task_type + text del task. Los nombres son semánticos — los
    # runners concretos resuelven aliases. Los consumers (intent classifier,
    # constraint compiler, model router) pueden leer estos hints para refinar
    # policy / binding filters sin depender de parsing textual.
    _TOOLS_BY_TASK_TYPE: Dict[str, List[str]] = {
        "orchestrator": ["plan_editor", "workflow_compose"],
        "security_review": ["code_reader", "security_scanner"],
        "review": ["code_reader", "diff_reader"],
        "research": ["web_search", "doc_reader"],
        "human_gate": ["hitl_gate"],
        "execution": ["file_writer", "shell_exec"],
    }

    # Token hints que añaden tools adicionales sobre los inferidos por task_type.
    _TOOL_TOKEN_HINTS: List[tuple[tuple[str, ...], str]] = [
        (("git ", "commit", "branch", "rebase"), "git_ops"),
        (("test ", "pytest", "jest", "unittest"), "test_runner"),
        (("docker", "kubernetes", "kubectl"), "container_ops"),
        (("sql", "database", "postgres", "mysql"), "db_query"),
        (("api", "http", "rest", "graphql"), "http_client"),
        (("patch", "refactor", "edit file"), "file_writer"),
        (("search codebase", "grep", "ripgrep"), "code_search"),
    ]

    @classmethod
    def _infer_required_tools(cls, task_type: str, text: str) -> List[str]:
        """Infiere la lista canonical de tools del task_type + tokens del text.

        BUGS_LATENTES §H2 fix. Devuelve lista de-duplicada preservando orden
        (primero los defaults por task_type, después los hints por token).
        Never raises — si no hay match, devuelve [].
        """
        tools: List[str] = list(cls._TOOLS_BY_TASK_TYPE.get(task_type, []))
        seen = set(tools)
        for tokens, tool in cls._TOOL_TOKEN_HINTS:
            if tool in seen:
                continue
            if any(tok in text for tok in tokens):
                tools.append(tool)
                seen.add(tool)
        return tools

    @classmethod
    def descriptor_from_task(cls, task: Dict[str, Any]) -> TaskDescriptor:
        normalized = cls.normalize_task(task)
        text = " ".join(
            [
                normalized["title"],
                normalized["description"],
                normalized["requested_role"],
                normalized["role_definition"],
                normalized.get("agent_rationale", ""),
            ]
        ).lower()
        task_type = "execution"
        task_semantic = "implementation"
        mutation_mode = "workspace"
        risk_band = "medium"

        if "orchestr" in text or normalized.get("scope") == "bridge":
            task_type = "orchestrator"
            task_semantic = "planning"
            mutation_mode = "none"
        elif any(token in text for token in ("security", "vulnerability", "hardening", "audit")):
            task_type = "security_review"
            task_semantic = "security"
            mutation_mode = "none"
            risk_band = "high"
        elif any(token in text for token in ("review", "validate", "qa", "verify")):
            task_type = "review"
            task_semantic = "review"
            mutation_mode = "none"
        elif any(token in text for token in ("research", "investigate", "analysis", "forensic", "docs")):
            task_type = "research"
            task_semantic = "research"
            mutation_mode = "none"
        elif any(token in text for token in ("ask approval", "approve", "human gate")):
            task_type = "human_gate"
            task_semantic = "approval"
            mutation_mode = "none"
            risk_band = "high"

        artifact_kind = "analysis" if mutation_mode == "none" else "code_change"
        complexity_band = "high" if normalized["depends_on"] or len(normalized["description"]) > 180 else "medium"
        parallelism_hint = "serial" if normalized["depends_on"] else "parallelizable"

        return TaskDescriptor(
            task_id=normalized["id"] or normalized["title"] or "task",
            title=normalized["title"] or "Task",
            description=normalized["description"],
            task_type=task_type,
            task_semantic=task_semantic,
            artifact_kind=artifact_kind,
            mutation_mode=mutation_mode,
            risk_band=risk_band,  # type: ignore[arg-type]
            required_tools=cls._infer_required_tools(task_type, text),
            path_scope=normalized["path_scope"],
            complexity_band=complexity_band,  # type: ignore[arg-type]
            parallelism_hint=parallelism_hint,  # type: ignore[arg-type]
            source_shape=normalized["source_shape"],  # type: ignore[arg-type]
        )
