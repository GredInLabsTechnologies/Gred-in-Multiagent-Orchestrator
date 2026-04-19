from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ...models.mesh import TaskFingerprint

logger = logging.getLogger("orchestrator.mesh.decomposer")

# Action keywords → action_class mapping
_ACTION_KEYWORDS: Dict[str, List[str]] = {
    "code_generation": ["write", "create", "generate", "implement", "add", "build"],
    "code_review": ["review", "check", "audit", "inspect", "validate", "lint"],
    "code_edit": ["edit", "modify", "update", "change", "refactor", "rename", "fix"],
    "test_execution": ["test", "run test", "pytest", "unittest", "verify"],
    "file_operation": ["read", "delete", "copy", "move", "list", "glob"],
    "search": ["search", "find", "grep", "locate", "look for"],
    "analysis": ["analyze", "explain", "summarize", "diagnose", "investigate"],
    "documentation": ["document", "readme", "docstring", "comment"],
    "deployment": ["deploy", "release", "publish", "push", "merge"],
    "shell": ["run", "execute", "shell", "command", "script", "bash"],
}

# File extension → target_type
_TARGET_TYPES: Dict[str, str] = {
    ".py": "python_file",
    ".ts": "typescript_file",
    ".tsx": "react_component",
    ".js": "javascript_file",
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".md": "documentation",
    ".txt": "documentation",
    ".sh": "script",
    ".cmd": "script",
    ".sql": "database",
    ".html": "template",
    ".css": "stylesheet",
}


class PlanDecomposer:
    """Decomposes orchestrator plan steps into atomic sub-tasks with TaskFingerprints."""

    def decompose(self, plan_steps: List[Dict[str, Any]]) -> List[TaskFingerprint]:
        fingerprints: List[TaskFingerprint] = []
        for step in plan_steps:
            fp = TaskFingerprint(
                action_class=self._classify_action(step),
                target_type=self._detect_target_type(step),
                domain_hints=self._extract_domain_hints(step),
                estimated_complexity=self._estimate_complexity(step),
                requires_context_kb=self._estimate_context(step),
                read_only=self._is_read_only(step),
            )
            fingerprints.append(fp)
        logger.debug("Decomposed %d steps into %d fingerprints", len(plan_steps), len(fingerprints))
        return fingerprints

    def _classify_action(self, step: Dict[str, Any]) -> str:
        text = self._step_text(step).lower()
        for action_class, keywords in _ACTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return action_class
        return "general"

    def _detect_target_type(self, step: Dict[str, Any]) -> str:
        text = self._step_text(step)
        # Look for file extensions in the step
        for ext, target in _TARGET_TYPES.items():
            if ext in text:
                return target
        # Check for path-like patterns
        if "/" in text or "\\" in text:
            return "file"
        return "unknown"

    def _extract_domain_hints(self, step: Dict[str, Any]) -> List[str]:
        text = self._step_text(step).lower()
        hints: List[str] = []
        domain_terms = [
            "api", "auth", "database", "ui", "frontend", "backend",
            "test", "security", "config", "model", "service", "router",
            "mesh", "thermal", "gics", "provider", "deployment",
        ]
        for term in domain_terms:
            if term in text:
                hints.append(term)
        return hints[:5]

    def _estimate_complexity(self, step: Dict[str, Any]) -> str:
        text = self._step_text(step)
        word_count = len(text.split())
        # Check for multi-step indicators
        has_multiple = any(w in text.lower() for w in ["and", "then", "also", "multiple", "several"])
        if word_count > 100 or has_multiple:
            return "complex"
        if word_count > 50:
            return "moderate"
        if word_count > 15:
            return "simple"
        return "trivial"

    def _estimate_context(self, step: Dict[str, Any]) -> int:
        context = step.get("context", {})
        if isinstance(context, dict):
            try:
                size = len(json.dumps(context, default=str))
                return size // 1024
            except Exception:
                pass
        return 0

    def _is_read_only(self, step: Dict[str, Any]) -> bool:
        text = self._step_text(step).lower()
        read_only_actions = ["read", "search", "find", "list", "analyze", "explain", "review", "check"]
        write_actions = ["write", "create", "edit", "modify", "delete", "update", "add", "fix"]
        for w in write_actions:
            if w in text:
                return False
        for r in read_only_actions:
            if r in text:
                return True
        return False

    @staticmethod
    def _step_text(step: Dict[str, Any]) -> str:
        parts = []
        for key in ("action", "intent", "description", "prompt", "objective", "title"):
            val = step.get(key)
            if val and isinstance(val, str):
                parts.append(val)
        return " ".join(parts) if parts else str(step)
