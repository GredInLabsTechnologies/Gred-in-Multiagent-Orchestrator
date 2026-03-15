from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, ClassVar, Dict, Optional

from tools.gimo_server.config import OPS_DATA_DIR
from tools.gimo_server.ops_models import ActionDraft
from tools.gimo_server.services.notification_service import NotificationService


class HitlGateService:
    CRITICAL_TOOLS: ClassVar[set[str]] = {
        "write_to_file",
        "replace_file_content",
        "run_command",
        "delete_file",
        "git_commit",
        "git_push",
        # Existing adapter/internal aliases
        "core_write_file",
        "shell_exec",
        "file_write",
        # Multi-agent review gate
        "review_agent_output",
        # Fractal complexity escalation
        "complexity_escalation",
    }

    _runtime_dir: ClassVar[Path] = OPS_DATA_DIR / "runtime"
    _drafts_path: ClassVar[Path] = _runtime_dir / "action_drafts.json"
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _waiters: ClassVar[Dict[str, asyncio.Future[str]]] = {}

    @classmethod
    def _load_all(cls) -> dict[str, dict[str, Any]]:
        if not cls._drafts_path.exists():
            return {}
        try:
            raw = json.loads(cls._drafts_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    @classmethod
    def _persist_all(cls, data: dict[str, dict[str, Any]]) -> None:
        cls._runtime_dir.mkdir(parents=True, exist_ok=True)
        tmp = cls._drafts_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cls._drafts_path)

    @classmethod
    def _risk_level(cls, tool: str, params: dict[str, Any]) -> str:
        if tool in {"delete_file", "git_push", "run_command", "shell_exec"}:
            return "critical"
        if tool in {"write_to_file", "replace_file_content", "core_write_file", "file_write", "git_commit"}:
            return "high"
        if params.get("path"):
            return "medium"
        return "low"

    @classmethod
    def list_drafts(cls, *, status: Optional[str] = None) -> list[ActionDraft]:
        drafts: list[ActionDraft] = []
        for payload in cls._load_all().values():
            try:
                draft = ActionDraft.model_validate(payload)
                if status and draft.status != status:
                    continue
                drafts.append(draft)
            except Exception:
                continue
        drafts.sort(key=lambda d: d.created_at, reverse=True)
        return drafts

    @classmethod
    def get_draft(cls, draft_id: str) -> Optional[ActionDraft]:
        payload = cls._load_all().get(draft_id)
        if not payload:
            return None
        try:
            return ActionDraft.model_validate(payload)
        except Exception:
            return None

    @classmethod
    async def _save_draft(cls, draft: ActionDraft) -> None:
        with cls._lock:
            data = cls._load_all()
            data[draft.id] = draft.model_dump(mode="json")
            cls._persist_all(data)

    @classmethod
    async def _resolve_draft(cls, draft_id: str, *, status: str, reason: Optional[str] = None) -> ActionDraft:
        with cls._lock:
            data = cls._load_all()
            if draft_id not in data:
                raise ValueError(f"Action draft {draft_id} not found")
            draft = ActionDraft.model_validate(data[draft_id])
            draft.status = status  # type: ignore[assignment]
            draft.decision_reason = reason
            draft.updated_at = datetime.now(timezone.utc)
            data[draft.id] = draft.model_dump(mode="json")
            cls._persist_all(data)

        fut = cls._waiters.pop(draft_id, None)
        if fut and not fut.done():
            fut.set_result("allow" if status == "approved" else "reject")
        return draft

    @classmethod
    async def approve(cls, draft_id: str, *, reason: Optional[str] = None) -> ActionDraft:
        return await cls._resolve_draft(draft_id, status="approved", reason=reason)

    @classmethod
    async def reject(cls, draft_id: str, *, reason: Optional[str] = None) -> ActionDraft:
        return await cls._resolve_draft(draft_id, status="rejected", reason=reason)

    @classmethod
    async def gate_tool_call(
        cls,
        *,
        agent_id: str,
        tool: str,
        params: dict[str, Any],
        timeout_seconds: float = 300.0,
    ) -> str:
        if tool not in cls.CRITICAL_TOOLS:
            return "allow"

        draft = ActionDraft(
            agent_id=agent_id,
            tool=tool,
            params=dict(params or {}),
            risk_level=cls._risk_level(tool, params or {}),
            status="pending",
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        cls._waiters[draft.id] = future

        await cls._save_draft(draft)
        await NotificationService.publish(
            "action_requires_approval",
            {
                "type": "action_requires_approval",
                "draft": draft.model_dump(mode="json"),
                "critical": True,
            },
        )

        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                await cls._resolve_draft(draft.id, status="timeout", reason="auto_reject_timeout")
            except Exception:
                pass
            return "reject"
