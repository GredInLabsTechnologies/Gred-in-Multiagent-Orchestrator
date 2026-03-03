from __future__ import annotations

import fnmatch
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..config import OPS_DATA_DIR
from ..ops_models import BaselineManifest, PolicyDecision, RuntimePolicyConfig


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


class RuntimePolicyService:
    """Phase-3 runtime policy evaluator with baseline hash enforcement."""

    POLICY_PATH: Path = OPS_DATA_DIR / "state" / "policy.json"
    BASELINE_PATH: Path = OPS_DATA_DIR / "runtime" / "baseline_manifest.json"

    @classmethod
    def _default_policy(cls) -> RuntimePolicyConfig:
        now = _utc_iso()
        return RuntimePolicyConfig(
            policy_schema_version="1.0",
            allowed_paths=["*"],
            forbidden_paths=[],
            forbidden_globs=[],
            forbidden_filetypes=[],
            max_files_changed=200,
            max_loc_changed=5000,
            require_human_review_if={},
            created_at=now,
            updated_at=now,
            policy_signature_alg="sha256",
            execution_mode_defaults={"auto_run": False},
        )

    @classmethod
    def _canonical_json(cls, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def compute_policy_hash(cls, config: RuntimePolicyConfig) -> str:
        canonical = cls._canonical_json(config.model_dump(mode="json"))
        return hashlib.sha256(canonical.encode("utf-8", errors="ignore")).hexdigest()

    @classmethod
    def ensure_runtime_files(cls) -> None:
        cls.POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

        if not cls.POLICY_PATH.exists():
            policy = cls._default_policy()
            cls.POLICY_PATH.write_text(policy.model_dump_json(indent=2), encoding="utf-8")

        if not cls.BASELINE_PATH.exists():
            raw_policy = json.loads(cls.POLICY_PATH.read_text(encoding="utf-8"))
            policy = RuntimePolicyConfig.model_validate(raw_policy)
            baseline = BaselineManifest(
                baseline_version="v1",
                policy_schema_version=policy.policy_schema_version,
                policy_hash_expected=cls.compute_policy_hash(policy),
            )
            cls.BASELINE_PATH.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_policy_config(cls) -> RuntimePolicyConfig:
        cls.ensure_runtime_files()
        raw = json.loads(cls.POLICY_PATH.read_text(encoding="utf-8"))
        return RuntimePolicyConfig.model_validate(raw)

    @classmethod
    def load_baseline_manifest(cls) -> BaselineManifest:
        cls.ensure_runtime_files()
        raw = json.loads(cls.BASELINE_PATH.read_text(encoding="utf-8"))
        return BaselineManifest.model_validate(raw)

    @classmethod
    def _matches_allowed(cls, path_value: str, patterns: Iterable[str]) -> bool:
        p = _normalize_path(path_value)
        for pattern in patterns:
            pat = _normalize_path(pattern)
            if not pat:
                continue
            if pat == "*":
                return True
            if fnmatch.fnmatch(p, pat):
                return True
            if p == pat or p.startswith(f"{pat}/"):
                return True
        return False

    @classmethod
    def evaluate_draft_policy(
        cls,
        *,
        path_scope: List[str],
        estimated_files_changed: Optional[int] = None,
        estimated_loc_changed: Optional[int] = None,
    ) -> PolicyDecision:
        policy = cls.load_policy_config()
        baseline = cls.load_baseline_manifest()
        runtime_hash = cls.compute_policy_hash(policy)
        expected_hash = baseline.policy_hash_expected
        triggered_rules: List[str] = []

        normalized_scope = [_normalize_path(p) for p in (path_scope or []) if _normalize_path(p)]
        files_changed = int(estimated_files_changed or 0)
        loc_changed = int(estimated_loc_changed or 0)

        decision_seed = cls._canonical_json(
            {
                "expected": expected_hash,
                "runtime": runtime_hash,
                "scope": normalized_scope,
                "files_changed": files_changed,
                "loc_changed": loc_changed,
            }
        )
        policy_decision_id = hashlib.sha256(decision_seed.encode("utf-8", errors="ignore")).hexdigest()[:16]

        if runtime_hash != expected_hash:
            triggered_rules.append("policy_hash_mismatch")
            return PolicyDecision(
                policy_decision_id=policy_decision_id,
                decision="deny",
                status_code="BASELINE_TAMPER_DETECTED",
                policy_hash_expected=expected_hash,
                policy_hash_runtime=runtime_hash,
                triggered_rules=triggered_rules,
            )

        for scope_path in normalized_scope:
            if not cls._matches_allowed(scope_path, policy.allowed_paths):
                triggered_rules.append(f"outside_allowed_paths:{scope_path}")

            for forbidden_path in policy.forbidden_paths:
                fp = _normalize_path(forbidden_path)
                if fp and (scope_path == fp or scope_path.startswith(f"{fp}/")):
                    triggered_rules.append(f"forbidden_path:{scope_path}")

            for forbidden_glob in policy.forbidden_globs:
                fg = _normalize_path(forbidden_glob)
                if fg and fnmatch.fnmatch(scope_path, fg):
                    triggered_rules.append(f"forbidden_glob:{scope_path}")

            suffix = Path(scope_path).suffix.lower()
            if suffix and suffix in {str(x).lower() for x in policy.forbidden_filetypes}:
                triggered_rules.append(f"forbidden_filetype:{scope_path}")

        if normalized_scope and len(normalized_scope) > policy.max_files_changed:
            triggered_rules.append("max_files_changed_scope_exceeded")
        if files_changed > policy.max_files_changed:
            triggered_rules.append("max_files_changed_estimated_exceeded")
        if loc_changed > policy.max_loc_changed:
            triggered_rules.append("max_loc_changed_exceeded")

        if triggered_rules:
            return PolicyDecision(
                policy_decision_id=policy_decision_id,
                decision="deny",
                status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
                policy_hash_expected=expected_hash,
                policy_hash_runtime=runtime_hash,
                triggered_rules=triggered_rules,
            )

        review_rules = policy.require_human_review_if or {}
        review_triggers: List[str] = []
        threshold_loc = review_rules.get("loc_gt")
        if isinstance(threshold_loc, int) and loc_changed > threshold_loc:
            review_triggers.append("require_human_review_if.loc_gt")

        review_globs = review_rules.get("path_globs") or []
        if isinstance(review_globs, list):
            for scope_path in normalized_scope:
                for glob_rule in review_globs:
                    if isinstance(glob_rule, str) and fnmatch.fnmatch(scope_path, _normalize_path(glob_rule)):
                        review_triggers.append(f"require_human_review_if.path_globs:{scope_path}")

        if review_triggers:
            return PolicyDecision(
                policy_decision_id=policy_decision_id,
                decision="review",
                status_code="HUMAN_APPROVAL_REQUIRED",
                policy_hash_expected=expected_hash,
                policy_hash_runtime=runtime_hash,
                triggered_rules=review_triggers,
            )

        return PolicyDecision(
            policy_decision_id=policy_decision_id,
            decision="allow",
            status_code="POLICY_ALLOW",
            policy_hash_expected=expected_hash,
            policy_hash_runtime=runtime_hash,
            triggered_rules=[],
        )
