from __future__ import annotations

import logging
import os
from typing import Any, Dict

from ..models.agent_routing import TaskConstraints, TaskDescriptor, TrustAuthorityResult
from ..utils.debug_mode import is_debug_mode
from .intent_classification_service import IntentClassificationService
from .providers.service import ProviderService
from .providers.topology_service import ProviderTopologyService
from .runtime_policy_service import RuntimePolicyService
from .workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.constraint_compiler")


class ConstraintCompilerService:
    _BASE_POLICIES_BY_SEMANTIC: Dict[str, list[str]] = {
        "planning": ["propose_only", "read_only"],
        "research": ["docs_research", "read_only"],
        "security": ["security_audit", "read_only"],
        "review": ["read_only", "security_audit"],
        "approval": ["propose_only"],
        "implementation": ["workspace_safe", "workspace_experiment"],
    }
    _FIRST_PARTY_SURFACES = frozenset({"operator", "cli", "tui", "web", "mcp"})
    _TRUST_UPGRADEABLE_SEMANTICS = frozenset({"planning", "approval"})
    _RUNTIME_ROLE_ALLOWLIST = frozenset({"worker", "executor", "reviewer", "researcher", "human_gate"})
    _RUNTIME_TOPOLOGY_HINTS = frozenset({"dynamic", "runtime", "adaptive"})
    _RISK_SCORE_BY_BAND = {
        "low": 10.0,
        "medium": 20.0,
        "high": 55.0,
    }

    @classmethod
    def _base_policies(cls, descriptor: TaskDescriptor) -> list[str]:
        return list(
            cls._BASE_POLICIES_BY_SEMANTIC.get(
                descriptor.task_semantic,
                cls._BASE_POLICIES_BY_SEMANTIC["implementation"],
            )
        )

    @classmethod
    def _trust_gate_policies(
        cls,
        *,
        allowed_policies: list[str],
        descriptor: TaskDescriptor,
        surface: str,
        task_context: Dict[str, Any],
    ) -> list[str]:
        """Upgrade base policies for trusted first-party surfaces via GICS signals.

        First-party surfaces with a reliable model get workspace_safe added to
        their allowed policies for planning/approval semantics.  Third-party
        surfaces and anomalous models keep the static constraints unchanged.
        Fail-open: if GICS is unavailable, the upgrade proceeds.
        """
        if descriptor.task_semantic not in cls._TRUST_UPGRADEABLE_SEMANTICS:
            return allowed_policies
        if surface not in cls._FIRST_PARTY_SURFACES:
            return allowed_policies

        # Check GICS for anomaly — block upgrade if model is unreliable
        if cls._is_gics_daemon_available():
            model_id = task_context.get("requested_model") or task_context.get("model_id")
            provider_type = task_context.get("requested_provider") or task_context.get("provider_type")
            if model_id and provider_type:
                try:
                    from .gics_service import GicsService
                    gics = GicsService()
                    reliability = gics.get_model_reliability(
                        provider_type=provider_type, model_id=model_id,
                    )
                    if reliability and (reliability.get("anomaly") or reliability.get("score", 0.5) < 0.5):
                        return allowed_policies  # Unreliable model — keep static constraints
                except Exception:
                    pass  # GICS error — fail-open to upgrade

        # Trust-gated upgrade: prepend workspace_safe so the router can select it
        if "workspace_safe" not in allowed_policies:
            return ["workspace_safe"] + allowed_policies
        return allowed_policies

    @classmethod
    def _safe_int(cls, value: Any) -> int | None:
        try:
            if value is None:
                return None
            out = int(value)
            return max(out, 0)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _safe_float(cls, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _resolve_surface_context(cls, task_context: Dict[str, Any]) -> tuple[str, str, list[str]]:
        notes: list[str] = []
        surface = str(task_context.get("surface") or WorkspacePolicyService.SURFACE_OPERATOR).strip().lower()
        if not surface:
            surface = WorkspacePolicyService.SURFACE_OPERATOR
        requested_mode = task_context.get("workspace_mode")
        try:
            workspace_mode = WorkspacePolicyService.resolve_effective_mode(
                requested_mode=requested_mode,
                surface=surface,
            )
        except ValueError:
            workspace_mode = str(requested_mode or "").strip().lower() or WorkspacePolicyService.MODE_EPHEMERAL
            notes.append("workspace_mode_rejected_for_surface")
            return surface, workspace_mode, notes
        return surface, workspace_mode, notes

    @classmethod
    def _derive_risk_score(cls, descriptor: TaskDescriptor, task_context: Dict[str, Any]) -> float:
        explicit = cls._safe_float(task_context.get("risk_score"))
        if explicit is not None:
            return max(explicit, 0.0)
        risk = cls._RISK_SCORE_BY_BAND.get(str(descriptor.risk_band or "").strip().lower(), 20.0)
        if descriptor.mutation_mode == "none":
            return min(risk, 20.0)
        return risk

    @classmethod
    def _apply_budget_envelope(
        cls,
        *,
        allowed_policies: list[str],
        task_context: Dict[str, Any],
        compiler_notes: list[str],
    ) -> tuple[list[str], str]:
        budget_mode = str(task_context.get("budget_mode") or "").strip().lower() or "standard"
        budget_usd = cls._safe_float(task_context.get("budget_usd"))

        narrowed = list(allowed_policies)
        if budget_mode in {"zero", "blocked"} or (budget_usd is not None and budget_usd <= 0):
            compiler_notes.append("budget_exhausted")
            return [], "blocked"
        if budget_mode in {"tight", "low"} or (budget_usd is not None and budget_usd < 1.0):
            narrowed = [policy for policy in narrowed if policy != "workspace_experiment"]
            compiler_notes.append("budget_clamped_experimental_policy")
            return narrowed, "tight"
        return narrowed, budget_mode

    @classmethod
    def _compile_binding_modes(
        cls,
        descriptor: TaskDescriptor,
        task_context: Dict[str, Any],
        *,
        requires_human_approval: bool,
        compiler_notes: list[str],
    ) -> list[str]:
        requested_binding_mode = str(task_context.get("binding_mode") or "").strip().lower()
        requested_role = str(task_context.get("requested_role") or "").strip().lower()
        has_dependencies = bool(task_context.get("depends_on"))
        topology_mode = str(task_context.get("topology_mode") or "").strip().lower()
        runtime_justified = has_dependencies or requires_human_approval or topology_mode in cls._RUNTIME_TOPOLOGY_HINTS
        runtime_role_allowed = requested_role in cls._RUNTIME_ROLE_ALLOWLIST or (
            not requested_role and descriptor.task_semantic != "planning"
        )

        if requested_binding_mode == "runtime":
            if runtime_justified and runtime_role_allowed:
                compiler_notes.append("runtime_binding_allowed")
                return ["runtime", "plan_time"]
            compiler_notes.append("runtime_binding_rejected_by_allowlist")
        elif runtime_justified and runtime_role_allowed and topology_mode in cls._RUNTIME_TOPOLOGY_HINTS:
            compiler_notes.append("runtime_binding_allowed_for_dynamic_topology")
            return ["plan_time", "runtime"]

        return ["plan_time"]

    @classmethod
    def _is_gics_daemon_available(cls) -> bool:
        """Fast non-blocking check: is the GICS daemon socket/pipe reachable?"""
        import os, sys
        if sys.platform == "win32":
            return os.path.exists(r"\\.\pipe\gics-daemon")
        # Unix: check socket file
        gics_home = os.path.join(os.path.expanduser("~"), ".gics")
        return os.path.exists(os.path.join(gics_home, "gics.sock"))

    # Mapping from task_semantic → benchmark dimension for fallback recommendations
    _SEMANTIC_TO_DIMENSION: Dict[str, str] = {
        "implementation": "coding",
        "planning": "reasoning",
        "research": "general_knowledge",
        "security": "expert_knowledge",
        "review": "reasoning",
        "approval": "instruction_following",
    }

    @classmethod
    def _build_recommendation(
        cls,
        *,
        task_type: str | None,
        task_semantic: str | None,
    ) -> dict | None:
        """Find the best alternative model for a task type.

        Tries operational history first (CapabilityProfileService), falls back
        to static benchmark dimensions (BenchmarkEnrichmentService).
        """
        # Layer 1: Operational history — real success data per model × task_type
        if task_type:
            try:
                from .capability_profile_service import CapabilityProfileService
                rec = CapabilityProfileService.recommend_model_for_task(
                    task_type=task_type, min_samples=2,
                )
                if rec:
                    rec["source"] = "operational_history"
                    return rec
            except Exception:
                pass

        # Layer 2: Benchmark data — static capability scores by dimension
        dimension = cls._SEMANTIC_TO_DIMENSION.get(task_semantic or "implementation", "coding")
        try:
            from .benchmark_enrichment_service import get_best_model_for_task
            # Use cached profiles (don't await refresh in sync context)
            from .benchmark_enrichment_service import _load_runtime_cache, _load_seed_file
            profiles = _load_runtime_cache() or _load_seed_file() or {}
            if profiles:
                best = get_best_model_for_task(dimension, profiles)
                if best:
                    return {"model_id": best, "source": "benchmark", "dimension": dimension}
        except Exception:
            pass

        return None

    @classmethod
    def _build_profile_summary(cls, *, provider_type: str, model_id: str) -> dict | None:
        """Build a compact strengths/weaknesses summary from CapabilityProfileService."""
        try:
            from .capability_profile_service import CapabilityProfileService
            profile = CapabilityProfileService.get_full_profile(
                provider_type=provider_type, model_id=model_id,
            )
            if not profile.strengths and not profile.weaknesses:
                return None
            return {
                "strengths": [
                    {"task_type": s.task_type, "success_rate": round(s.success_rate, 2), "samples": s.samples}
                    for s in profile.strengths[:3]
                ],
                "weaknesses": [
                    {"task_type": w.task_type, "success_rate": round(w.success_rate, 2), "samples": w.samples}
                    for w in profile.weaknesses[:3]
                ],
                "total_samples": profile.total_samples,
                "overall_success_rate": round(profile.overall_success_rate, 2),
            }
        except Exception:
            return None

    @classmethod
    def apply_trust_authority(
        cls,
        execution_policy: str,
        *,
        model_id: str | None = None,
        provider_type: str | None = None,
        workspace_root: str | None = None,
        task_type: str | None = None,
        task_semantic: str | None = None,
    ) -> TrustAuthorityResult:
        """Evaluate trust and reliability signals — annotate, never block.

        Returns TrustAuthorityResult with the ORIGINAL policy unchanged.
        GICS anomaly signals become advisory metadata (warning, score,
        recommendation), not policy overrides.  Only explicit user-configured
        limits should hard-block.

        Fail-open: if signals unavailable, returns policy with no metadata.
        """
        if is_debug_mode():
            logger.warning(
                "Trust authority: DEBUG mode — bypassing GICS/trust checks for %s/%s",
                provider_type, model_id,
            )
            return TrustAuthorityResult(policy=execution_policy, debug_bypass=True)

        requires_approval = False
        trust_warning = None
        reliability_score = None
        anomaly_detected = False
        recommended_alternative = None
        model_profile_summary = None

        # Check GICS model reliability — anomaly becomes metadata, not a block
        if model_id and provider_type and cls._is_gics_daemon_available():
            try:
                from .gics_service import GicsService
                gics = GicsService()
                reliability = gics.get_model_reliability(
                    provider_type=provider_type, model_id=model_id,
                )
                if reliability:
                    reliability_score = float(reliability.get("score", 0.5) or 0.5)
                    if reliability.get("anomaly"):
                        anomaly_detected = True
                        failure_streak = int(reliability.get("failure_streak", 0) or 0)
                        trust_warning = (
                            f"Model {provider_type}/{model_id} has anomaly detected "
                            f"(failure_streak={failure_streak}, score={reliability_score:.2f}). "
                            f"Consider using an alternative model for this task."
                        )
                        logger.info(
                            "Trust authority: model %s/%s anomaly — annotating with metadata (policy unchanged: %s)",
                            provider_type, model_id, execution_policy,
                        )
                        # Enrich with recommendation and profile
                        recommended_alternative = cls._build_recommendation(
                            task_type=task_type, task_semantic=task_semantic,
                        )
                        model_profile_summary = cls._build_profile_summary(
                            provider_type=provider_type, model_id=model_id,
                        )
            except Exception:
                pass  # Fail-open

        # Check TrustEngine workspace dimension
        if workspace_root and cls._is_gics_daemon_available():
            try:
                from .storage_service import StorageService
                from .trust_engine import TrustEngine
                storage = StorageService()
                engine = TrustEngine(storage.trust)
                trust_record = engine.query_dimension(f"workspace:{workspace_root}")
                trust_policy = trust_record.get("policy")
                if trust_policy is None:
                    pass  # New workspace, no data — full authority
                elif trust_policy == "blocked":
                    trust_warning = (trust_warning or "") + f" Workspace {workspace_root} is blocked by TrustEngine."
                    logger.info("Trust authority: workspace %s blocked — annotating (policy unchanged)", workspace_root)
                elif trust_policy == "require_review":
                    requires_approval = True
            except Exception:
                pass  # Fail-open

        return TrustAuthorityResult(
            policy=execution_policy,
            requires_approval=requires_approval,
            trust_warning=trust_warning,
            reliability_score=reliability_score,
            anomaly_detected=anomaly_detected,
            recommended_alternative=recommended_alternative,
            model_profile_summary=model_profile_summary,
        )

    @classmethod
    def compile_for_descriptor(
        cls,
        descriptor: TaskDescriptor,
        task_context: Dict[str, Any] | None = None,
    ) -> TaskConstraints:
        context = dict(task_context or {})
        compiler_notes: list[str] = []
        allowed_policies = cls._base_policies(descriptor)
        surface, workspace_mode, surface_notes = cls._resolve_surface_context(context)
        compiler_notes.extend(surface_notes)

        # Wire 1: Trust-gated policy upgrade for first-party surfaces
        pre_upgrade = list(allowed_policies)
        allowed_policies = cls._trust_gate_policies(
            allowed_policies=allowed_policies,
            descriptor=descriptor,
            surface=surface,
            task_context=context,
        )
        if allowed_policies != pre_upgrade:
            compiler_notes.append("trust_gate_upgraded_to_workspace_safe")

        if "workspace_mode_rejected_for_surface" in compiler_notes:
            return TaskConstraints(
                allowed_policies=[],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
                surface=surface,
                workspace_mode=workspace_mode,
                policy_decision="deny",
                policy_status_code="WORKSPACE_MODE_NOT_ALLOWED",
                budget_mode="blocked",
                compiler_notes=compiler_notes,
            )

        if descriptor.mutation_mode == "workspace" and not WorkspacePolicyService.allows_experimental_policy(workspace_mode):
            allowed_policies = [policy for policy in allowed_policies if policy != "workspace_experiment"]
            compiler_notes.append("workspace_experiment_disallowed_for_workspace_mode")

        allowed_policies, budget_mode = cls._apply_budget_envelope(
            allowed_policies=allowed_policies,
            task_context=context,
            compiler_notes=compiler_notes,
        )

        requires_human_approval = descriptor.task_semantic == "approval" or bool(context.get("requires_human_approval"))
        policy_decision = "allow"
        policy_status_code = "POLICY_ALLOW"

        estimated_files_changed, estimated_loc_changed = RuntimePolicyService.estimate_change_scope(
            path_scope=descriptor.path_scope,
            complexity_band=descriptor.complexity_band,
            estimated_files_changed=cls._safe_int(context.get("estimated_files_changed")),
            estimated_loc_changed=cls._safe_int(context.get("estimated_loc_changed")),
        )

        if descriptor.mutation_mode == "workspace":
            policy_audit = RuntimePolicyService.evaluate_draft_policy(
                path_scope=descriptor.path_scope,
                estimated_files_changed=estimated_files_changed,
                estimated_loc_changed=estimated_loc_changed,
            )
            policy_decision = policy_audit.decision
            policy_status_code = policy_audit.status_code
            if policy_audit.decision == "deny":
                allowed_policies = []
                compiler_notes.append("runtime_policy_denied_scope")
            elif policy_audit.decision == "review":
                requires_human_approval = True
                compiler_notes.append("runtime_policy_requires_human_review")

        declared_intent = str(context.get("intent_class") or "").strip() or IntentClassificationService.default_intent_for_descriptor(
            task_semantic=descriptor.task_semantic,
            mutation_mode=descriptor.mutation_mode,
        )
        risk_score = cls._derive_risk_score(descriptor, context)
        intent_audit = IntentClassificationService.evaluate(
            intent_declared=declared_intent,
            path_scope=descriptor.path_scope,
            risk_score=risk_score,
            policy_decision=policy_decision,
            policy_status_code=policy_status_code,
        )
        if intent_audit.execution_decision == "DRAFT_REJECTED_FORBIDDEN_SCOPE":
            allowed_policies = []
            compiler_notes.append("intent_rejected_scope")
        elif intent_audit.execution_decision == "RISK_SCORE_TOO_HIGH":
            allowed_policies = []
            compiler_notes.append("intent_rejected_high_risk")
        elif intent_audit.execution_decision == "HUMAN_APPROVAL_REQUIRED":
            requires_human_approval = True
            compiler_notes.append("intent_requires_human_approval")

        provider_cfg = ProviderService.get_config()
        topology_bindings = ProviderTopologyService.bindings_for_descriptor(provider_cfg, descriptor)
        constrained_bindings = ProviderTopologyService.constrain_bindings(
            topology_bindings,
            requested_provider=context.get("requested_provider"),
            requested_model=context.get("requested_model"),
        )
        if constrained_bindings != topology_bindings:
            compiler_notes.append("binding_candidates_narrowed_by_request")

        allowed_binding_modes = cls._compile_binding_modes(
            descriptor,
            context,
            requires_human_approval=requires_human_approval,
            compiler_notes=compiler_notes,
        )

        return TaskConstraints(
            allowed_policies=allowed_policies,  # type: ignore[arg-type]
            allowed_binding_modes=allowed_binding_modes,  # type: ignore[arg-type]
            requires_human_approval=requires_human_approval,
            allowed_bindings=constrained_bindings,
            surface=surface,
            workspace_mode=workspace_mode,
            policy_decision=policy_decision,
            policy_status_code=policy_status_code,
            intent_effective=intent_audit.intent_effective,
            budget_mode=budget_mode,
            compiler_notes=compiler_notes,
        )
