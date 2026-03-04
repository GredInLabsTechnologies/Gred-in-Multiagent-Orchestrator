from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.config import ConfigDict


ProviderType = Literal[
    "ollama_local",
    "ollama",
    "vllm",
    "llama-cpp",
    "tgi",
    "openai",
    "anthropic",
    "google",
    "mistral",
    "cohere",
    "deepseek",
    "qwen",
    "moonshot",
    "zai",
    "minimax",
    "baidu",
    "tencent",
    "bytedance",
    "iflytek",
    "01-ai",
    "codex",
    "claude",
    "groq",
    "openrouter",
    "together",
    "fireworks",
    "replicate",
    "huggingface",
    "azure-openai",
    "aws-bedrock",
    "vertex-ai",
    "custom_openai_compatible",
]


GimoItemType = Literal["text", "tool_call", "tool_result", "diff", "thought", "error"]
GimoItemStatus = Literal["started", "delta", "completed", "error"]
GimoThreadStatus = Literal["active", "archived", "deleted"]


import uuid

class GimoItem(BaseModel):
    id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")
    type: GimoItemType
    content: str = ""
    status: GimoItemStatus = "completed"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GimoTurn(BaseModel):
    id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    agent_id: str
    items: List[GimoItem] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GimoThread(BaseModel):
    id: str = Field(default_factory=lambda: f"thread_{uuid.uuid4().hex[:8]}")
    title: str = "New Conversation"
    workspace_root: str
    turns: List[GimoTurn] = Field(default_factory=list)
    status: GimoThreadStatus = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentProfile(BaseModel):
    role: str
    goal: str
    backstory: Optional[str] = None
    model: str = "qwen2.5-coder:32b"
    system_prompt: str
    instructions: List[str] = []


class OpsTask(BaseModel):
    id: str
    title: str
    scope: str
    depends: List[str] = []
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    description: str
    agent_assignee: Optional[AgentProfile] = None


class OpsPlan(BaseModel):
    id: str
    title: str
    workspace: str
    created: str
    objective: str
    tasks: List[OpsTask]
    constraints: List[str] = []


class OpsDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = None
    content: Optional[str] = None
    status: Literal["draft", "rejected", "approved", "error"] = "draft"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OpsApproved(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    draft_id: str
    prompt: str
    provider: Optional[str] = None
    content: str
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: Optional[str] = None


OpsRunStatus = Literal[
    "pending",
    "running",
    "done",
    "error",
    "cancelled",
    "MERGE_LOCKED",
    "MERGE_CONFLICT",
    "VALIDATION_FAILED_TESTS",
    "VALIDATION_FAILED_LINT",
    "RISK_SCORE_TOO_HIGH",
    "BASELINE_TAMPER_DETECTED",
    "PIPELINE_TIMEOUT",
    "WORKTREE_CORRUPTED",
    "ROLLBACK_EXECUTED",
    "WORKER_CRASHED_RECOVERABLE",
    "HUMAN_APPROVAL_REQUIRED",
]


class OpsRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    approved_id: str
    status: OpsRunStatus = "pending"
    repo_id: Optional[str] = None
    draft_id: Optional[str] = None
    commit_base: Optional[str] = None
    commit_before: Optional[str] = None
    commit_after: Optional[str] = None
    stage: Optional[str] = None
    run_key: Optional[str] = None
    risk_score: Optional[float] = None
    policy_decision_id: Optional[str] = None
    lock_id: Optional[str] = None
    lock_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    log: List[Dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderEntry(BaseModel):
    # Legacy-compatible input (kept for gradual migration)
    type: str = "custom_openai_compatible"
    # Canonical provider taxonomy
    provider_type: Optional[ProviderType] = None
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    auth_mode: Optional[str] = None
    auth_ref: Optional[str] = None
    model: str = "gpt-4o-mini"
    model_id: Optional[str] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_model_fields(self) -> "ProviderEntry":
        if self.model_id and (not self.model or self.model == "gpt-4o-mini"):
            self.model = self.model_id
        if not self.model_id:
            self.model_id = self.model
        return self


class NormalizedModelInfo(BaseModel):
    id: str
    label: str
    context_window: Optional[int] = None
    size: Optional[str] = None
    installed: bool = False
    downloadable: bool = False
    quality_tier: Optional[str] = None


class ProviderModelsCatalogResponse(BaseModel):
    provider_type: ProviderType
    installed_models: List[NormalizedModelInfo] = Field(default_factory=list)
    available_models: List[NormalizedModelInfo] = Field(default_factory=list)
    recommended_models: List[NormalizedModelInfo] = Field(default_factory=list)
    can_install: bool = False
    install_method: Literal["api", "command", "manual"] = "manual"
    auth_modes_supported: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ProviderModelInstallRequest(BaseModel):
    model_id: str


class ProviderModelInstallResponse(BaseModel):
    status: Literal["queued", "running", "done", "error"]
    message: str
    progress: Optional[float] = None
    job_id: Optional[str] = None


class ProviderValidateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    org: Optional[str] = None
    account: Optional[str] = None


class ProviderValidateResponse(BaseModel):
    valid: bool
    health: str
    effective_model: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error_actionable: Optional[str] = None



class McpServerConfig(BaseModel):
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class ProviderConfig(BaseModel):
    """Provider config persisted to disk.

    Matches the schema described in docs/OPS_RUNTIME_PLAN_v2.md.
    """

    schema_version: int = 2
    active: str
    providers: Dict[str, ProviderEntry]
    mcp_servers: Dict[str, McpServerConfig] = Field(default_factory=dict)
    # v2 snapshot fields (non-sensitive)
    provider_type: Optional[ProviderType] = None
    model_id: Optional[str] = None
    auth_mode: Optional[str] = None
    auth_ref: Optional[str] = None
    last_validated_at: Optional[str] = None
    effective_state: Dict[str, Any] = Field(default_factory=dict)
    capabilities_snapshot: Dict[str, Any] = Field(default_factory=dict)


class OpsCreateDraftRequest(BaseModel):
    # Legacy shape (kept for backward compatibility)
    prompt: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

    # Phase-1 contract shape (GPT Actions integration)
    objective: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    repo_context: Dict[str, Any] = Field(default_factory=dict)
    execution: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_phase1_contract(self) -> "OpsCreateDraftRequest":
        if self._is_legacy_mode():
            self._validate_legacy_mode()
        else:
            self._validate_contract_mode()
        return self

    def _is_legacy_mode(self) -> bool:
        return bool(self.prompt and str(self.prompt).strip())

    def _validate_legacy_mode(self) -> None:
        intent = str((self.context or {}).get("intent_class") or "").strip()
        if intent not in PHASE4_INTENT_CLASSES:
            raise ValueError("context.intent_class is missing or invalid")

    def _validate_contract_mode(self) -> None:
        if not self.objective or not str(self.objective).strip():
            raise ValueError("objective is required when prompt is not provided")

        if not isinstance(self.constraints, list):
            raise ValueError("constraints must be a list")
        if not isinstance(self.acceptance_criteria, list) or not self.acceptance_criteria:
            raise ValueError("acceptance_criteria must be a non-empty list")

        rc = self.repo_context or {}
        if not isinstance(rc, dict):
            raise ValueError("repo_context must be an object")
        if not rc.get("target_branch"):
            raise ValueError("repo_context.target_branch is required")
        if not isinstance(rc.get("path_scope"), list) or not rc.get("path_scope"):
            raise ValueError("repo_context.path_scope must be a non-empty list")

        ex = self.execution or {}
        if not isinstance(ex, dict):
            raise ValueError("execution must be an object")
        intent = str(ex.get("intent_class") or "").strip()
        if intent not in PHASE4_INTENT_CLASSES:
            raise ValueError("execution.intent_class is missing or invalid")

        return self


class OpsUpdateDraftRequest(BaseModel):
    prompt: Optional[str] = None
    content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


PHASE4_INTENT_CLASSES = {
    "DOC_UPDATE",
    "TEST_ADD",
    "SAFE_REFACTOR",
    "FEATURE_ADD_LOW_RISK",
    "ARCH_CHANGE",
    "SECURITY_CHANGE",
    "CORE_RUNTIME_CHANGE",
}

ExecutionDecisionCode = Literal[
    "AUTO_RUN_ELIGIBLE",
    "HUMAN_APPROVAL_REQUIRED",
    "RISK_SCORE_TOO_HIGH",
    "DRAFT_REJECTED_FORBIDDEN_SCOPE",
    "PRIMARY_MODEL_SUCCESS",
    "FALLBACK_MODEL_USED",
]


class IntentDecisionAudit(BaseModel):
    """Phase-4 auditable decision payload persisted in draft context."""

    intent_declared: str
    intent_effective: str
    risk_score: float = 0.0
    decision_reason: str
    execution_decision: ExecutionDecisionCode


StrategyFinalStatus = Literal[
    "PRIMARY_MODEL_SUCCESS",
    "FALLBACK_MODEL_USED",
]


class ModelStrategyAudit(BaseModel):
    """Phase-6 auditable model strategy decision payload."""

    strategy_decision_id: str
    strategy_reason: str
    model_attempted: str
    failure_reason: str
    final_model_used: str
    fallback_used: bool
    final_status: StrategyFinalStatus


# --- Jules-Style GraphState MVP Models ---

from enum import Enum

class IntentClass(str, Enum):
    feature = "feature"
    bugfix = "bugfix"
    refactor = "refactor"
    chore = "chore"

class DelegationStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"

class QaVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"

class RepoSnapshot(BaseModel):
    provider: str
    repo: str
    base_ref: str
    worktree_id: Optional[str] = None

class RepoContext(BaseModel):
    stack: List[str] = Field(default_factory=list)
    commands: List[str] = Field(default_factory=list)
    paths_of_interest: List[str] = Field(default_factory=list)
    env_notes: Optional[str] = None

class ContractExecution(BaseModel):
    intent_class: IntentClass

class StrictContract(BaseModel):
    objective: str = Field(min_length=10)
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(min_length=1)
    execution: ContractExecution
    out_of_scope: List[str] = Field(default_factory=list)

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_actionable_criteria(cls, v: List[str]) -> List[str]:
        # Minimum validation: must not be just empty strings
        for c in v:
            if not c.strip():
                raise ValueError("Acceptance criteria cannot be empty strings.")
        return v

class Delegation(BaseModel):
    role: str
    prompt: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    expected_outputs: Dict[str, Any] = Field(default_factory=dict)
    status: DelegationStatus = DelegationStatus.pending
    artifacts: List[str] = Field(default_factory=list)

class CommandRun(BaseModel):
    cmd: str
    cwd: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TestRun(BaseModel):
    name: str
    status: Literal["passed", "failed", "skipped"]
    duration_ms: int

class DiffRef(BaseModel):
    path: str
    sha: Optional[str] = None
    summary: str

class Evidence(BaseModel):
    commands_run: List[CommandRun] = Field(default_factory=list)
    test_results: List[TestRun] = Field(default_factory=list)
    diffs: List[DiffRef] = Field(default_factory=list)

class Failure(BaseModel):
    criterion: str
    reason: str
    evidence_ref: Optional[str] = None
    suggested_fix: Optional[str] = None

class QaState(BaseModel):
    verdict: Optional[QaVerdict] = None
    failures: List[Failure] = Field(default_factory=list)

class GraphState(BaseModel):
    """
    Central artifact for Jules-style multi-agent orchestration.
    """
    state_version: Literal["0.1"] = "0.1"
    
    user_request_raw: str
    repo_snapshot: Optional[RepoSnapshot] = None
    repo_context: RepoContext = Field(default_factory=RepoContext)
    
    contract: Optional[StrictContract] = None
    delegations: Dict[str, Delegation] = Field(default_factory=dict)
    
    evidence: Evidence = Field(default_factory=Evidence)
    qa: QaState = Field(default_factory=QaState)


class ProviderBudget(BaseModel):
    """Budget limit per provider, set by the user."""
    provider: str
    max_cost_usd: Optional[float] = None
    period: Literal["daily", "weekly", "monthly", "total"] = "monthly"

    @field_validator("max_cost_usd")
    @classmethod
    def validate_max_cost(cls, v):
        if v is not None and v < 0:
            raise ValueError("max_cost_usd must be >= 0")
        return v


class CascadeConfig(BaseModel):
    """User-configured cascade behavior."""
    enabled: bool = False
    min_tier: str = "local"
    max_tier: str = "opus"
    quality_threshold: int = 65
    max_escalations: int = 2

    @field_validator("quality_threshold")
    @classmethod
    def validate_quality(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError("quality_threshold must be between 0 and 100")
        return v

    @field_validator("max_escalations")
    @classmethod
    def validate_escalations(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_escalations must be >= 0")
        return v


class EcoModeConfig(BaseModel):
    """User-configured eco-mode behavior."""
    mode: Literal["off", "binary", "smart"] = "off"
    floor_tier: str = "local"
    confidence_threshold_aggressive: float = 0.85
    confidence_threshold_moderate: float = 0.70

    @field_validator("confidence_threshold_aggressive", "confidence_threshold_moderate")
    @classmethod
    def validate_thresholds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("Confidence thresholds must be between 0.0 and 1.0")
        return v


class UserEconomyConfig(BaseModel):
    """All token economy settings. User controls everything."""
    autonomy_level: Literal["manual", "advisory", "guided", "autonomous"] = "manual"
    global_budget_usd: Optional[float] = None
    provider_budgets: List[ProviderBudget] = Field(default_factory=list)
    alert_thresholds: List[int] = Field(default_factory=lambda: [50, 25, 10])
    cascade: CascadeConfig = Field(default_factory=CascadeConfig)
    eco_mode: EcoModeConfig = Field(default_factory=EcoModeConfig)
    allow_roi_routing: bool = False
    model_floor: Optional[str] = None
    model_ceiling: Optional[str] = None
    cache_enabled: bool = False
    cache_ttl_hours: int = 24
    show_cost_predictions: bool = False
    provider_model_map: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    hardware_thresholds: Optional[Dict[str, Dict[str, int]]] = None
    allow_local_override: bool = False

    @field_validator("global_budget_usd")
    @classmethod
    def validate_budget(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("global_budget_usd must be >= 0")
        return v

    @field_validator("alert_thresholds")
    @classmethod
    def validate_alerts(cls, v: List[int]) -> List[int]:
        for t in v:
            if not (0 <= t <= 100):
                raise ValueError("Alert thresholds must be percentages between 0 and 100")
        return sorted(set(v), reverse=True)

    @field_validator("cache_ttl_hours")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cache_ttl_hours must be >= 0")
        return v


class CostEvent(BaseModel):
    id: str
    workflow_id: str
    node_id: str
    model: str
    provider: str
    task_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    quality_score: float = 0.0
    cascade_level: int = 0
    cache_hit: bool = False
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QualityRating(BaseModel):
    """Formal quality rating for LLM outputs."""
    score: int = Field(ge=0, le=100)
    alerts: List[str] = Field(default_factory=list)
    heuristics: Dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CascadeResult(BaseModel):
    """Result of a cascading execution."""
    final_output: Any
    cascade_chain: List[Dict[str, Any]] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    savings: float = 0.0
    success: bool = True


class CascadeStatsEntry(BaseModel):
    task_type: str
    total_calls: int = 0
    cascaded_calls: int = 0
    avg_cascade_depth: float = 0.0
    total_spent: float = 0.0


class CacheStats(BaseModel):
    total_calls: int = 0
    cache_hits: int = 0
    hit_rate: float = 0.0
    estimated_savings_usd: float = 0.0


class RoiLeaderboardEntry(BaseModel):
    model: str
    task_type: str
    roi_score: float = 0.0
    avg_quality: float = 0.0
    avg_cost: float = 0.0
    sample_count: int = 0


class CostAnalytics(BaseModel):
    daily_costs: List[Dict[str, Any]] = Field(default_factory=list)
    by_model: List[Dict[str, Any]] = Field(default_factory=list)
    by_task_type: List[Dict[str, Any]] = Field(default_factory=list)
    by_provider: List[Dict[str, Any]] = Field(default_factory=list)
    roi_leaderboard: List[Dict[str, Any]] = Field(default_factory=list)
    cascade_stats: List[Dict[str, Any]] = Field(default_factory=list)
    cache_stats: Dict[str, Any] = Field(default_factory=dict)
    total_savings: float = 0.0


class BudgetForecast(BaseModel):
    scope: str = "global"
    current_spend: float = 0.0
    limit: Optional[float] = None
    remaining: Optional[float] = None
    remaining_pct: Optional[float] = None
    burn_rate_hourly: float = 0.0
    hours_to_exhaustion: Optional[float] = None
    alert_level: Literal["none", "warning", "critical"] = "none"


class MasteryStatus(BaseModel):
    eco_mode_enabled: bool
    total_savings_usd: float
    efficiency_score: float
    tips: List[str]


class OpsConfig(BaseModel):
    """Global OPS runtime configuration persisted to .orch_data/ops/config.json."""

    default_auto_run: bool = False
    draft_cleanup_ttl_days: int = 7
    max_concurrent_runs: int = 3
    operator_can_generate: bool = False
    economy: UserEconomyConfig = Field(default_factory=UserEconomyConfig)


class OpsApproveResponse(BaseModel):
    """Response for approve endpoint — includes optional auto-created run."""

    approved: OpsApproved
    run: Optional[OpsRun] = None


class OpsCreateRunRequest(BaseModel):
    approved_id: str


class WorkflowNode(BaseModel):
    id: str
    type: Literal[
        "llm_call",
        "tool_call",
        "human_review",
        "eval",
        "transform",
        "sub_graph",
        "agent_task",
        "contract_check",
    ]
    config: Dict[str, Any] = Field(default_factory=dict)
    agent: Optional[str] = None
    timeout: Optional[int] = None
    retries: int = 0


class WorkflowEdge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    condition: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class WorkflowGraph(BaseModel):
    id: str
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    state_schema: Dict[str, Any] = Field(default_factory=dict)


class WorkflowCheckpoint(BaseModel):
    node_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: Dict[str, Any]
    output: Any
    status: Literal["completed", "failed"]


class WorkflowState(BaseModel):
    version: int = 1
    data: Dict[str, Any] = Field(default_factory=dict)
    checkpoints: List[WorkflowCheckpoint] = Field(default_factory=list)


class WorkflowExecuteRequest(BaseModel):
    workflow: WorkflowGraph
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    persist_checkpoints: bool = True
    workflow_timeout_seconds: Optional[int] = None


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


class ContractCheck(BaseModel):
    type: Literal["file_exists", "tests_pass", "function_exists", "no_new_vulnerabilities", "custom"]
    params: Dict[str, Any] = Field(default_factory=dict)


class WorkflowContract(BaseModel):
    pre_conditions: List[ContractCheck] = Field(default_factory=list)
    post_conditions: List[ContractCheck] = Field(default_factory=list)
    rollback: List[Dict[str, Any]] = Field(default_factory=list)
    blast_radius: Literal["low", "medium", "high", "critical"] = "low"


class CircuitBreakerConfigModel(BaseModel):
    window: int = Field(default=20, ge=1)
    failure_threshold: int = Field(default=5, ge=1)
    recovery_probes: int = Field(default=3, ge=1)
    cooldown_seconds: int = Field(default=300, ge=0)


class ToolEntry(BaseModel):
    name: str
    description: str = ""
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    risk: Literal["read", "write", "destructive"] = "read"
    estimated_cost: float = 0.0
    requires_hitl: bool = False
    allowed_roles: List[str] = Field(default_factory=lambda: ["operator", "admin"])
    metadata: Dict[str, Any] = Field(default_factory=dict)


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


class RuntimePolicyConfig(BaseModel):
    """Phase-3 runtime policy contract (baseline enforcement)."""

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


class EvalGoldenCase(BaseModel):
    case_id: str
    input_state: Dict[str, Any] = Field(default_factory=dict)
    expected_state: Dict[str, Any] = Field(default_factory=dict)
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)


class EvalDataset(BaseModel):
    workflow_id: str
    name: str
    description: Optional[str] = None
    cases: List[EvalGoldenCase] = Field(default_factory=list)


class EvalJudgeConfig(BaseModel):
    enabled: bool = False
    mode: Literal["heuristic"] = "heuristic"
    output_key: Optional[str] = None


class EvalGateConfig(BaseModel):
    min_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    min_avg_score: float = Field(default=1.0, ge=0.0, le=1.0)


class EvalRunRequest(BaseModel):
    workflow: WorkflowGraph
    dataset: EvalDataset
    judge: EvalJudgeConfig = Field(default_factory=EvalJudgeConfig)
    gate: EvalGateConfig = Field(default_factory=EvalGateConfig)
    case_limit: Optional[int] = Field(default=None, ge=1)


class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    input_state: Dict[str, Any] = Field(default_factory=dict)
    expected_state: Dict[str, Any] = Field(default_factory=dict)
    actual_state: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None


class EvalRunReport(BaseModel):
    eval_run_id: Optional[int] = None
    workflow_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float = Field(ge=0.0, le=1.0)
    avg_score: float = Field(ge=0.0, le=1.0)
    gate_passed: bool
    gate: EvalGateConfig
    results: List[EvalCaseResult] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    run_id: int
    workflow_id: str
    gate_passed: bool
    pass_rate: float = Field(ge=0.0, le=1.0)
    avg_score: float = Field(ge=0.0, le=1.0)
    total_cases: int
    passed_cases: int
    failed_cases: int
    created_at: str


class EvalRunDetail(BaseModel):
    run_id: int
    workflow_id: str
    created_at: str
    report: Optional[EvalRunReport] = None
