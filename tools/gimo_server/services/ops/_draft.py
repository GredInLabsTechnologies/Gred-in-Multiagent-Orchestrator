from __future__ import annotations

import logging
import os
import time
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional

from ...ops_models import OpsApproved, OpsDraft
from ..task_descriptor_service import TaskDescriptorService
from ._base import _utcnow

logger = logging.getLogger("orchestrator.ops")


class DraftMixin:
    """Draft CRUD + approve/reject lifecycle."""

    @staticmethod
    def _canonicalize_structured_content(
        content: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not isinstance(content, str):
            return content
        ctx = context or {}
        if not (ctx.get("structured") or ctx.get("custom_plan_id")):
            return content
        return TaskDescriptorService.maybe_canonicalize_plan_content(content)

    @classmethod
    def list_drafts(
        cls,
        *,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[OpsDraft]:
        if not cls.DRAFTS_DIR.exists():
            return []
        out: List[OpsDraft] = []
        for f in cls.DRAFTS_DIR.glob(cls._DRAFT_GLOB):
            try:
                draft = OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))
                if status and draft.status != status:
                    continue
                out.append(draft)
            except Exception as exc:
                logger.warning("Failed to parse draft %s: %s", f.name, exc)
        sorted_drafts = sorted(out, key=lambda d: d.created_at, reverse=True)
        if offset is not None:
            sorted_drafts = sorted_drafts[offset:]
        if limit is not None:
            sorted_drafts = sorted_drafts[:limit]
        return sorted_drafts

    @classmethod
    def create_draft(
        cls,
        prompt: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
        content: Optional[str] = None,
        status: str = "draft",
        error: Optional[str] = None,
    ) -> OpsDraft:
        cls.ensure_dirs()
        draft_id = f"d_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
        canonical_content = cls._canonicalize_structured_content(content, context)
        draft = OpsDraft(
            id=draft_id,
            prompt=prompt,
            context=context or {},
            provider=provider,
            content=canonical_content,
            status=status,  # type: ignore[arg-type]
            error=error,
            created_at=_utcnow(),
        )
        cls._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        if cls._gics:
            try:
                cls._gics.put(f"ops:draft:{draft.id}", draft.model_dump())
            except Exception as e:
                logger.error("Failed to push draft %s to GICS: %s", draft.id, e)
        return draft

    @classmethod
    def get_draft(cls, draft_id: str) -> Optional[OpsDraft]:
        f = cls._draft_path(draft_id)
        if not f.exists():
            return None
        return OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))

    @classmethod
    def update_draft(cls, draft_id: str, *, prompt: Optional[str], content: Optional[str], context: Optional[Dict[str, Any]]) -> OpsDraft:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            effective_context = context if context is not None else draft.context
            if prompt is not None:
                draft.prompt = prompt
            if content is not None:
                draft.content = cls._canonicalize_structured_content(content, effective_context)
            if context is not None:
                draft.context = context
                if content is None:
                    draft.content = cls._canonicalize_structured_content(draft.content, draft.context)
            cls._draft_path(draft_id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            return draft

    @classmethod
    def reject_draft(cls, draft_id: str) -> OpsDraft:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            draft.status = "rejected"  # type: ignore[assignment]
            cls._draft_path(draft_id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            return draft

    @classmethod
    def approve_draft(cls, draft_id: str, *, approved_by: Optional[str] = None) -> OpsApproved:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            if draft.status == "rejected":
                raise ValueError("Cannot approve a rejected draft")

            # Idempotent contract: if already approved, return existing approved record.
            if draft.status == "approved":
                existing = cls._find_latest_approved_for_draft(draft.id)
                if existing:
                    return existing

            draft.content = cls._canonicalize_structured_content(draft.content, draft.context)

            approved_id = f"a_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
            approved = OpsApproved(
                id=approved_id,
                draft_id=draft.id,
                prompt=draft.prompt,
                provider=draft.provider,
                content=draft.content or "",
                approved_at=_utcnow(),
                approved_by=approved_by,
            )

            # Atomically move: write approved then mark draft as approved
            cls._approved_path(approved.id).write_text(
                approved.model_dump_json(indent=2), encoding="utf-8"
            )
            draft.status = "approved"  # type: ignore[assignment]
            cls._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

            if cls._gics:
                 try:
                     cls._gics.put(f"ops:approved:{approved.id}", approved.model_dump())
                     cls._gics.put(f"ops:draft:{draft.id}", draft.model_dump())
                 except Exception as e:
                     logger.error("Failed to push approved %s to GICS: %s", approved.id, e)
            return approved

    @classmethod
    def cleanup_old_drafts(cls) -> int:
        """Remove rejected/error drafts older than config.draft_cleanup_ttl_days."""
        config = cls.get_config()
        ttl_days = config.draft_cleanup_ttl_days
        if ttl_days <= 0 or not cls.DRAFTS_DIR.exists():
            return 0
        now = _utcnow()
        cutoff = now - timedelta(days=ttl_days)
        cleaned = 0
        for f in cls.DRAFTS_DIR.glob(cls._DRAFT_GLOB):
            try:
                draft = OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))
                if draft.status in ("rejected", "error") and draft.created_at.replace(tzinfo=timezone.utc) < cutoff:
                    f.unlink(missing_ok=True)
                    cleaned += 1
            except Exception:
                continue
        return cleaned
