from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from ..config import get_settings
from .lifecycle_errors import LifecycleProofError, RunNotFoundError
from .ops_service import OpsService


def _validated_task_spec(run: Any) -> Dict[str, Any]:
    return dict(getattr(run, "validated_task_spec", None) or {})


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def get_run_with_context(run_id: str) -> Tuple[Any, Dict[str, Any]]:
    run = OpsService.get_run(run_id)
    if not run:
        raise RunNotFoundError(f"Run {run_id} not found")

    approved = None
    if getattr(run, "approved_id", None):
        try:
            approved = OpsService.get_approved(run.approved_id)
        except Exception:
            approved = None

    draft = None
    if approved and getattr(approved, "draft_id", None):
        try:
            draft = OpsService.get_draft(approved.draft_id)
        except Exception:
            draft = None

    draft_context = dict((draft.context if draft else {}) or {})
    return run, draft_context


def resolve_base_commit(run_id: str, run: Any, draft_context: Dict[str, Any]) -> str:
    candidates: list[tuple[str, str]] = []

    for source, value in (
        ("validated_task_spec.base_commit", _validated_task_spec(run).get("base_commit")),
        ("draft.context.base_commit", draft_context.get("base_commit")),
        ("draft.context.commit_base", draft_context.get("commit_base")),
        ("run.commit_base", getattr(run, "commit_base", None)),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        if source == "run.commit_base" and text.upper() == "HEAD":
            continue
        candidates.append((source, text))

    if not candidates:
        raise LifecycleProofError(
            f"Base commit for run {run_id} cannot be proven from canonical evidence. Failing closed."
        )

    values = {value for _, value in candidates}
    if len(values) != 1:
        sources = ", ".join(f"{source}={value}" for source, value in candidates)
        raise LifecycleProofError(
            f"Base commit for run {run_id} is inconsistent across canonical evidence: {sources}"
        )

    return candidates[0][1]


def resolve_workspace_path(
    run_id: str,
    run: Any,
    draft_context: Dict[str, Any],
    *,
    required: bool,
    require_exists: bool,
) -> Path | None:
    candidates: list[tuple[str, Path]] = []

    for source, value in (
        ("validated_task_spec.workspace_path", _validated_task_spec(run).get("workspace_path")),
        ("draft.context.workspace_path", draft_context.get("workspace_path")),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        candidates.append((source, Path(text).expanduser().resolve()))

    if not candidates:
        if required:
            raise LifecycleProofError(f"No canonical workspace_path found for run {run_id}")
        return None

    unique_paths = {str(path) for _, path in candidates}
    if len(unique_paths) != 1:
        sources = ", ".join(f"{source}={path}" for source, path in candidates)
        raise LifecycleProofError(
            f"Workspace path for run {run_id} is inconsistent across canonical evidence: {sources}"
        )

    workspace_path = candidates[0][1]
    settings = get_settings()
    repo_root = Path(settings.repo_root_dir).resolve()
    allowed_roots = [
        Path(settings.ephemeral_repos_dir).resolve(),
        Path(settings.worktrees_dir).resolve(),
    ]

    if workspace_path == repo_root:
        raise LifecycleProofError(
            f"Workspace path for run {run_id} resolves to repo_root and is not purge/review-safe: {workspace_path}"
        )

    if not any(_is_relative_to(workspace_path, root) for root in allowed_roots):
        raise LifecycleProofError(
            f"Workspace path for run {run_id} is outside canonical workspace roots: {workspace_path}"
        )

    if require_exists and not workspace_path.exists():
        raise LifecycleProofError(f"Workspace path {workspace_path} does not exist")

    if workspace_path.exists() and not workspace_path.is_dir():
        raise LifecycleProofError(f"Workspace path {workspace_path} is not a directory")

    return workspace_path
