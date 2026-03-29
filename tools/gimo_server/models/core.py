from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

# Runtime imports needed by Pydantic model fields (must not be TYPE_CHECKING-only)
from .agent import AgentProfile
from .economy import UserEconomyConfig

if TYPE_CHECKING:
    pass

OpsRunStatus = Literal[
    "pending",
    "running",
    "done",
    "error",
    "cancelled",
    "awaiting_subagents",
    "awaiting_review",
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
    "AWAITING_MERGE",
]

class OpsCreateRunRequest(BaseModel):
    approved_id: str


class ChildRunRequest(BaseModel):
    parent_run_id: str
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)
    agent_profile: Optional[str] = None

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
    parent_run_id: Optional[str] = None
    child_run_ids: List[str] = Field(default_factory=list)
    awaiting_count: int = 0
    attempt: int = 1
    rerun_of: Optional[str] = None
    child_prompt: Optional[str] = None
    child_context: Optional[Dict[str, Any]] = None
    spawn_depth: int = 0          # Fractal depth (0 = root orchestrator)
    model_tier: Optional[int] = None  # quality_tier of the model assigned to this run
    validated_task_spec: Optional[Dict[str, Any]] = None # Phase 5B: Required for execution
    agent_preset: Optional[str] = None  # P10: Routing metadata persisted from draft
    execution_policy_name: Optional[str] = None  # P10: Execution policy persisted from draft
    routing_snapshot: Optional[Dict[str, Any]] = None  # P10: Serialized routing decision

class ExecutorReport(BaseModel):
    run_id: str
    agent_id: str
    modified_files: List[str] = Field(default_factory=list)
    safety_summary: str
    rollback_plan: List[str]
    timestamp: str

    @field_validator("rollback_plan")
    @classmethod
    def must_have_rollback(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("rollback_plan required")
        return v

class RefactorConfig(BaseModel):
    """Feature flags for the GIMO refactor phase."""
    engine_v1_enabled: bool = False
    tool_calling_artifacts_enabled: bool = False
    journal_replay_enabled: bool = False
    adaptive_risk_enabled: bool = False
    self_healing_enabled: bool = False

class OpsConfig(BaseModel):
    default_auto_run: bool = False
    # Intent types that are never eligible for auto_run, regardless of default_auto_run.
    # These intents require human review before execution.
    auto_run_excluded_intents: List[str] = Field(
        default_factory=lambda: ["MERGE_REQUEST", "SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"]
    )
    draft_cleanup_ttl_days: int = 7
    max_concurrent_runs: int = 3
    operator_can_generate: bool = False
    economy: Optional[UserEconomyConfig] = None
    refactor: RefactorConfig = Field(default_factory=RefactorConfig)
    ui_show_ids_events: bool = True
    ui_enable_chat_investigation: bool = True


class OpsCreateDraftRequest(BaseModel):
    prompt: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    objective: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    repo_context: Dict[str, Any] = Field(default_factory=dict)
    execution: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_phase1_contract(self) -> "OpsCreateDraftRequest":
        if self.prompt and str(self.prompt).strip():
            self._validate_legacy_intent()
        else:
            self._validate_contract_mode()
        return self

    def _validate_legacy_intent(self) -> None:
        from .policy import PHASE4_INTENT_CLASSES
        intent = str((self.context or {}).get("intent_class") or "").strip()
        if intent and intent not in PHASE4_INTENT_CLASSES:
            raise ValueError("context.intent_class is invalid")

    def _validate_contract_mode(self) -> None:
        from .policy import PHASE4_INTENT_CLASSES
        if not self.objective or not str(self.objective).strip():
            raise ValueError("objective is required when prompt is not provided")
        if not isinstance(self.acceptance_criteria, list) or not self.acceptance_criteria:
            raise ValueError("acceptance_criteria must be a non-empty list")
        ex = self.execution or {}
        intent = str(ex.get("intent_class") or "").strip()
        if intent not in PHASE4_INTENT_CLASSES:
            raise ValueError("execution.intent_class is missing or invalid")

class OpsUpdateDraftRequest(BaseModel):
    prompt: Optional[str] = None
    content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

class OpsApproveResponse(BaseModel):
    approved: OpsApproved
    run: Optional[OpsRun] = None

class RepoEntry(BaseModel):
    name: str
    path: str

class RunEvent(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: str
    data: Dict[str, Any] = Field(default_factory=dict)

class RunLogEntry(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: str
    msg: str
    run_key: Optional[str] = None


class PurgeReceipt(BaseModel):
    """Phase 6B: Canonical proof of run state removal."""
    run_id: str
    purged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    removed_categories: List[str] # e.g. ["logs", "events", "workspace"]
    retained_metadata_hash: str
    success: bool


class StatusResponse(BaseModel):
    version: str
    uptime_seconds: float


class UiStatusResponse(BaseModel):
    version: str
    uptime_seconds: float
    allowlist_count: int
    last_audit_line: Optional[str] = None
    service_status: str


class VitaminizeResponse(BaseModel):
    status: str
    created_files: List[str] = Field(default_factory=list)
    active_repo: str
