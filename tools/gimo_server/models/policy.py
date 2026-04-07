from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class CircuitBreakerConfigModel(BaseModel):
    """API-facing model for circuit breaker configuration (mirrors internal CircuitBreakerConfig)."""
    window: int = 20
    failure_threshold: int = 5
    recovery_probes: int = 3
    cooldown_seconds: int = 300


PHASE4_INTENT_CLASSES = {
    "DOC_UPDATE", "TEST_ADD", "SAFE_REFACTOR", "FEATURE_ADD_LOW_RISK",
    "ARCH_CHANGE", "SECURITY_CHANGE", "CORE_RUNTIME_CHANGE",
}

ExecutionDecisionCode = Literal[
    "AUTO_RUN_ELIGIBLE", "HUMAN_APPROVAL_REQUIRED", "RISK_SCORE_TOO_HIGH",
    "DRAFT_REJECTED_FORBIDDEN_SCOPE", "PRIMARY_MODEL_SUCCESS", "FALLBACK_MODEL_USED",
]

class IntentDecisionAudit(BaseModel):
    intent_declared: str
    intent_effective: str
    risk_score: float = 0.0
    decision_reason: str
    execution_decision: ExecutionDecisionCode

class RuntimePolicyConfig(BaseModel):
    policy_schema_version: str = "1.0"
    allowed_paths: List[str] = Field(default_factory=list)
    forbidden_paths: List[str] = Field(default_factory=list)
    forbidden_globs: List[str] = Field(default_factory=list)
    forbidden_filetypes: List[str] = Field(default_factory=list)
    max_files_changed: int = Field(default=200, ge=1)
    max_loc_changed: int = Field(default=5000, ge=1)
    require_human_review_if: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    policy_signature_alg: Optional[str] = None
    policy_hash_previous: Optional[str] = None
    execution_mode_defaults: Dict[str, Any] = Field(default_factory=dict)

class BaselineManifest(BaseModel):
    baseline_version: str = "v1"
    policy_schema_version: str = "1.0"
    policy_hash_expected: str

class PolicyDecision(BaseModel):
    policy_decision_id: str
    decision: Literal["allow", "review", "deny"]
    status_code: str
    policy_hash_expected: str
    policy_hash_runtime: str
    triggered_rules: List[str] = Field(default_factory=list)

class PolicyRuleMatch(BaseModel):
    tool: str = "*"
    context: str = "*"

class PolicyRule(BaseModel):
    match: PolicyRuleMatch = Field(default_factory=PolicyRuleMatch)
    action: Literal["allow", "deny", "require_review"] = "allow"
    override: Optional[Literal["never_auto_approve"]] = None
    min_trust_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

class PolicyConfig(BaseModel):
    rules: List[PolicyRule] = Field(default_factory=list)

class TrustRecord(BaseModel):
    dimension_key: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    policy: Literal["allow", "require_review", "blocked", "auto_approve"]
    approvals: int = 0
    failures: int = 0
    streak: int = 0
    circuit_state: Literal["open", "closed", "half-open"] = "closed"
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TrustDashboardEntry(BaseModel):
    """Canonical row shape for the trust dashboard, aligned with the renderer.

    R17 Cluster E.1: unifies the backend output with the field names consumed
    by gimo_cli/render.py::TRUST_STATUS (``dimension``, ``score``, ``state``)
    so dashboard columns render. Legacy field aliases (``dimension_key``,
    ``circuit_state``) are preserved for the web UI hook
    (useSecurityService.ts) and MCP bridge consumers that already key off
    them.
    """

    dimension: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    state: str
    policy: str
    approvals: int = 0
    rejections: int = 0
    failures: int = 0
    auto_approvals: int = 0
    streak: int = 0
    last_updated: Optional[str] = None
    dimension_key: str
    circuit_state: str
    circuit_opened_at: Optional[str] = None

class TrustEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dimension_key: str  # "tool|path|model|task_type"
    tool: str
    context: str
    model: str
    task_type: Optional[str] = None
    outcome: Literal["approved", "rejected", "error", "timeout", "auto_approved"]
    actor: str
    post_check_passed: bool = True
    duration_ms: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

StrategyFinalStatus = Literal[
    "PRIMARY_MODEL_SUCCESS",
    "FALLBACK_MODEL_USED",
]

class ModelStrategyAudit(BaseModel):
    strategy_decision_id: str
    strategy_reason: str
    model_attempted: str
    failure_reason: str
    final_model_used: str
    fallback_used: bool
    final_status: StrategyFinalStatus
