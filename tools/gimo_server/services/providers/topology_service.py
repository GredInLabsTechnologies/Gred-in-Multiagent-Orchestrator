from __future__ import annotations

import shutil
from typing import Any, Callable, Dict

from ...models.agent_routing import TaskDescriptor
from ...ops_models import ProviderConfig, ProviderEntry, ProviderRoleBinding, ProviderRolesConfig


class ProviderTopologyService:
    """Topology-centric helpers extracted from ProviderService.

    Keeps role normalization and account-provider auto-injection isolated so the
    ProviderService entrypoint has lower blast radius.
    """

    @staticmethod
    def has_account_mode_provider(
        providers: Dict[str, ProviderEntry],
        provider_type: str,
        normalize_provider_type: Callable[[str | None], str],
    ) -> bool:
        canonical = normalize_provider_type(provider_type)
        for entry in providers.values():
            entry_type = normalize_provider_type(entry.provider_type or entry.type)
            auth_mode = str(entry.auth_mode or "").strip().lower()
            if entry_type == canonical and auth_mode == "account":
                return True
        return False

    @classmethod
    def inject_cli_account_providers(
        cls,
        providers: Dict[str, ProviderEntry],
        *,
        normalize_provider_type: Callable[[str | None], str],
        capabilities_for: Callable[[str | None], Dict[str, Any]],
    ) -> Dict[str, ProviderEntry]:
        out = dict(providers)
        specs = [
            {
                "provider_type": "codex",
                "provider_id": "codex-account",
                "binary": "codex",
                "display_name": "Codex Account Mode",
                "model": "gpt-5-codex",
            },
            {
                "provider_type": "claude",
                "provider_id": "claude-account",
                "binary": "claude",
                "display_name": "Claude Account Mode",
                "model": "claude-3-7-sonnet-latest",
            },
        ]

        for spec in specs:
            provider_type = str(spec["provider_type"])
            provider_id = str(spec["provider_id"])
            binary = str(spec["binary"])
            if shutil.which(binary) is None:
                continue
            if provider_id in out:
                continue
            if cls.has_account_mode_provider(out, provider_type, normalize_provider_type):
                continue

            model = str(spec["model"])
            out[provider_id] = ProviderEntry(
                type=provider_type,
                provider_type=provider_type,
                display_name=str(spec["display_name"]),
                auth_mode="account",
                model=model,
                model_id=model,
                capabilities=capabilities_for(provider_type),
            )

        return out

    @staticmethod
    def _get_entry_model(provider_id: str, providers: Dict[str, ProviderEntry]) -> str:
        entry = providers.get(provider_id)
        return entry.configured_model_id() if entry else ""

    @classmethod
    def _create_binding(
        cls,
        provider_id: str,
        model: str | None,
        providers: Dict[str, ProviderEntry],
    ) -> ProviderRoleBinding | None:
        if not provider_id or provider_id not in providers:
            return None
        resolved_model = str(model or "").strip() or cls._get_entry_model(provider_id, providers)
        return ProviderRoleBinding(provider_id=provider_id, model=resolved_model) if resolved_model else None

    @classmethod
    def _get_roles_from_schema(
        cls,
        cfg: ProviderConfig,
        providers: Dict[str, ProviderEntry],
    ) -> tuple[ProviderRoleBinding | None, list[ProviderRoleBinding]]:
        orchestrator = None
        workers = []
        if cfg.roles:
            orchestrator = cls._create_binding(cfg.roles.orchestrator.provider_id, cfg.roles.orchestrator.model, providers)
            for worker in cfg.roles.workers:
                if wb := cls._create_binding(worker.provider_id, worker.model, providers):
                    workers.append(wb)
        return orchestrator, workers

    @classmethod
    def _get_legacy_roles(
        cls,
        cfg: ProviderConfig,
        providers: Dict[str, ProviderEntry],
    ) -> tuple[ProviderRoleBinding | None, list[ProviderRoleBinding]]:
        orch_provider = cfg.orchestrator_provider or cfg.active
        orch_model = cfg.orchestrator_model or cfg.model_id
        orch = cls._create_binding(str(orch_provider or ""), orch_model, providers)

        if not orch and cfg.active in providers:
            orch = cls._create_binding(cfg.active, None, providers)

        workers = []
        if worker := cls._create_binding(str(cfg.worker_provider or ""), cfg.worker_model, providers):
            workers.append(worker)

        return orch, workers

    @classmethod
    def _get_fallback_orchestrator(
        cls,
        cfg: ProviderConfig,
        providers: Dict[str, ProviderEntry],
    ) -> ProviderRoleBinding | None:
        fallback_provider = cfg.active if cfg.active in providers else next(iter(providers.keys()), "")
        return cls._create_binding(fallback_provider, None, providers)

    @staticmethod
    def _deduplicate_workers(
        orchestrator: ProviderRoleBinding | None,
        worker_bindings: list[ProviderRoleBinding],
    ) -> list[ProviderRoleBinding]:
        workers: list[ProviderRoleBinding] = []
        seen_workers: set[tuple[str, str]] = set()
        for candidate in worker_bindings:
            key = (candidate.provider_id, candidate.model)
            if key in seen_workers:
                continue
            if orchestrator and key == (orchestrator.provider_id, orchestrator.model):
                continue
            seen_workers.add(key)
            workers.append(candidate)
        return workers

    @classmethod
    def normalize_roles(
        cls,
        cfg: ProviderConfig,
        providers: Dict[str, ProviderEntry],
    ) -> ProviderRolesConfig:
        orchestrator, worker_bindings = cls._get_roles_from_schema(cfg, providers)

        if not orchestrator:
            legacy_orch, legacy_workers = cls._get_legacy_roles(cfg, providers)
            orchestrator = legacy_orch
            worker_bindings.extend(legacy_workers)

        if not orchestrator:
            orchestrator = cls._get_fallback_orchestrator(cfg, providers)

        if not orchestrator:
            raise ValueError("Provider topology requires a valid orchestrator binding")

        workers = cls._deduplicate_workers(orchestrator, worker_bindings)
        return ProviderRolesConfig(orchestrator=orchestrator, workers=workers)

    @classmethod
    def bindings_for_descriptor(
        cls,
        cfg: ProviderConfig | None,
        descriptor: TaskDescriptor,
    ) -> list[ProviderRoleBinding]:
        if not cfg:
            return [ProviderRoleBinding(provider_id="auto", model="auto")]

        providers = dict(cfg.providers or {})
        if not providers:
            return [ProviderRoleBinding(provider_id="auto", model="auto")]

        roles = cls.normalize_roles(cfg, providers)
        if descriptor.task_semantic in {"planning", "approval"} or descriptor.task_type == "orchestrator":
            return [roles.orchestrator]
        if roles.workers:
            return list(roles.workers)
        return [roles.orchestrator]

    @classmethod
    def constrain_bindings(
        cls,
        bindings: list[ProviderRoleBinding],
        *,
        requested_provider: str | None = None,
        requested_model: str | None = None,
    ) -> list[ProviderRoleBinding]:
        candidates = list(bindings or [])
        if not candidates:
            return [ProviderRoleBinding(provider_id="auto", model="auto")]

        provider = str(requested_provider or "").strip()
        model = str(requested_model or "").strip()
        provider_requested = bool(provider and provider != "auto")
        model_requested = bool(model and model != "auto")

        if not provider_requested and not model_requested:
            return candidates

        filtered = [
            binding
            for binding in candidates
            if (not provider_requested or binding.provider_id == provider)
            and (not model_requested or binding.model == model)
        ]
        if filtered:
            return filtered

        if provider_requested:
            provider_only = [binding for binding in candidates if binding.provider_id == provider]
            if provider_only:
                return provider_only

        if model_requested:
            model_only = [binding for binding in candidates if binding.model == model]
            if model_only:
                return model_only

        return candidates
