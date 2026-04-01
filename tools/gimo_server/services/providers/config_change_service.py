from __future__ import annotations

from typing import Callable, Optional

from ...ops_models import ProviderConfig


class ProviderConfigChangeService:
    """Helpers to detect provider config drift and invalidate dependent caches."""

    @classmethod
    def compare_provider(
        cls,
        *,
        prev,
        cur,
        changed_types: set[str],
        normalize_provider_type: Callable[[str | None], str],
        invalidate_catalog_cache: Callable[[str, str], None],
    ) -> None:
        prev_type = normalize_provider_type(prev.provider_type or prev.type) if prev else None
        cur_type = normalize_provider_type(cur.provider_type or cur.type) if cur else None

        if prev_type:
            changed_types.add(prev_type)
        if cur_type:
            changed_types.add(cur_type)

        if prev and cur and (prev.auth_ref != cur.auth_ref or prev.auth_mode != cur.auth_mode):
            if cur_type:
                invalidate_catalog_cache(cur_type, "credentials_changed")

    @classmethod
    def get_changed_provider_types(
        cls,
        *,
        before: Optional[ProviderConfig],
        current: ProviderConfig,
        normalize_provider_type: Callable[[str | None], str],
        invalidate_catalog_cache: Callable[[str, str], None],
    ) -> set[str]:
        changed_types: set[str] = set()
        if not before:
            for entry in current.providers.values():
                changed_types.add(normalize_provider_type(entry.provider_type or entry.type))
            return changed_types

        all_ids = set(before.providers.keys()) | set(current.providers.keys())
        for provider_id in all_ids:
            cls.compare_provider(
                prev=before.providers.get(provider_id),
                cur=current.providers.get(provider_id),
                changed_types=changed_types,
                normalize_provider_type=normalize_provider_type,
                invalidate_catalog_cache=invalidate_catalog_cache,
            )
        return changed_types
