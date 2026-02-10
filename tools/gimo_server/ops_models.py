from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class OpsTask(BaseModel):
    id: str
    title: str
    scope: str
    depends: List[str] = []
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    description: str


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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OpsApproved(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    draft_id: str
    prompt: str
    provider: Optional[str] = None
    content: str
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None


class OpsRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    approved_id: str
    status: Literal["pending", "running", "done", "error", "cancelled"] = "pending"
    log: List[Dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProviderEntry(BaseModel):
    type: Literal["openai_compat", "anthropic", "gemini"]
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str


class ProviderConfig(BaseModel):
    """Provider config persisted to disk.

    Matches the schema described in docs/OPS_RUNTIME_PLAN_v2.md.
    """

    active: str
    providers: Dict[str, ProviderEntry]


class OpsCreateDraftRequest(BaseModel):
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)


class OpsUpdateDraftRequest(BaseModel):
    prompt: Optional[str] = None
    content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class OpsConfig(BaseModel):
    """Global OPS runtime configuration persisted to .orch_data/ops/config.json."""

    default_auto_run: bool = False
    draft_cleanup_ttl_days: int = 7
    max_concurrent_runs: int = 3
    operator_can_generate: bool = False


class OpsApproveResponse(BaseModel):
    """Response for approve endpoint — includes optional auto-created run."""

    approved: OpsApproved
    run: Optional[OpsRun] = None


class OpsCreateRunRequest(BaseModel):
    approved_id: str
