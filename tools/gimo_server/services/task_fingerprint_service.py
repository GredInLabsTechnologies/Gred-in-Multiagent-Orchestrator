from __future__ import annotations

import hashlib
import json

from ..models.agent_routing import TaskDescriptor, TaskFingerprintParts


class TaskFingerprintService:
    @staticmethod
    def _sanitize_paths(paths: list[str]) -> list[str]:
        sanitized: list[str] = []
        for path in paths:
            normalized = str(path or "").replace("\\", "/").strip().strip("/")
            if not normalized:
                continue
            parts = normalized.split("/")
            sanitized.append("/".join(parts[:3]))
        return sorted(set(sanitized))

    @classmethod
    def build_parts(cls, descriptor: TaskDescriptor) -> TaskFingerprintParts:
        return TaskFingerprintParts(
            task_type=descriptor.task_type,
            task_semantic=descriptor.task_semantic,
            artifact_kind=descriptor.artifact_kind,
            mutation_mode=descriptor.mutation_mode,
            risk_band=descriptor.risk_band,
            complexity_band=descriptor.complexity_band,
            required_tools=sorted(set(descriptor.required_tools)),
            path_scope=cls._sanitize_paths(descriptor.path_scope),
        )

    @classmethod
    def fingerprint_for_descriptor(cls, descriptor: TaskDescriptor) -> str:
        parts = cls.build_parts(descriptor)
        payload = json.dumps(parts.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:24]
