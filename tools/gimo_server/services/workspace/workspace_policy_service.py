from __future__ import annotations

from typing import Final


class WorkspacePolicyService:
    """Canonical workspace and orchestrator policy by surface."""

    SURFACE_CHATGPT_APP: Final[str] = "chatgpt_app"
    SURFACE_OPERATOR: Final[str] = "operator"

    MODE_EPHEMERAL: Final[str] = "ephemeral"
    MODE_SOURCE_REPO: Final[str] = "source_repo"
    ORCHESTRATOR_AUTHORITY_GIMO: Final[str] = "gimo"
    ORCHESTRATOR_AUTHORITY_CHATGPT_APP: Final[str] = "chatgpt_app"

    _ALIASES: Final[dict[str, str]] = {
        "ephemeral": MODE_EPHEMERAL,
        "isolated": MODE_EPHEMERAL,
        "source_repo": MODE_SOURCE_REPO,
        "original": MODE_SOURCE_REPO,
        "original_repo": MODE_SOURCE_REPO,
    }

    @classmethod
    def normalize_mode(cls, mode: str | None) -> str:
        raw = str(mode or "").strip().lower()
        if not raw:
            return cls.MODE_EPHEMERAL
        normalized = cls._ALIASES.get(raw)
        if normalized is None:
            raise ValueError(f"Unsupported workspace_mode: {mode}")
        return normalized

    @classmethod
    def allowed_modes_for_surface(cls, surface: str | None) -> tuple[str, ...]:
        if str(surface or "").strip().lower() == cls.SURFACE_CHATGPT_APP:
            return (cls.MODE_EPHEMERAL,)
        return (cls.MODE_EPHEMERAL, cls.MODE_SOURCE_REPO)

    @classmethod
    def orchestrator_authority_for_surface(cls, surface: str | None) -> str:
        if str(surface or "").strip().lower() == cls.SURFACE_CHATGPT_APP:
            return cls.ORCHESTRATOR_AUTHORITY_CHATGPT_APP
        return cls.ORCHESTRATOR_AUTHORITY_GIMO

    @classmethod
    def can_surface_select_orchestrator(cls, surface: str | None) -> bool:
        return str(surface or "").strip().lower() != cls.SURFACE_CHATGPT_APP

    @classmethod
    def can_surface_select_worker_model(cls, surface: str | None) -> bool:
        return str(surface or "").strip().lower() != cls.SURFACE_CHATGPT_APP

    @classmethod
    def allows_experimental_policy(cls, mode: str | None) -> bool:
        return cls.normalize_mode(mode) == cls.MODE_SOURCE_REPO

    @classmethod
    def default_metadata_for_surface(cls, surface: str | None) -> dict[str, str | bool]:
        normalized_surface = str(surface or "").strip().lower() or cls.SURFACE_OPERATOR
        return {
            "surface": normalized_surface,
            "workspace_mode": cls.resolve_effective_mode(requested_mode=None, surface=normalized_surface),
            "orchestrator_authority": cls.orchestrator_authority_for_surface(normalized_surface),
            "orchestrator_selection_allowed": cls.can_surface_select_orchestrator(normalized_surface),
            "worker_model_selection_allowed": cls.can_surface_select_worker_model(normalized_surface),
        }

    @classmethod
    def resolve_effective_mode(cls, *, requested_mode: str | None, surface: str | None) -> str:
        normalized = cls.normalize_mode(requested_mode)
        if normalized not in cls.allowed_modes_for_surface(surface):
            raise ValueError(
                f"workspace_mode '{normalized}' is not allowed for surface '{surface or cls.SURFACE_OPERATOR}'"
            )
        return normalized
