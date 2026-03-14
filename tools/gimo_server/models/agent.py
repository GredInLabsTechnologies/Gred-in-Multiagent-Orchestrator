from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set
from pydantic import BaseModel, Field

AgentRole = Literal["orchestrator", "worker", "external_action"]
AgentChannel = Literal["cli", "provider_api", "gpt_actions", "mcp_remote"]

class AgentProfile(BaseModel):
    role: str
    goal: str
    backstory: Optional[str] = None
    model: str = "qwen2.5-coder:32b"
    system_prompt: str
    instructions: List[str] = []

class AgentActionEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str
    agent_role: AgentRole
    channel: AgentChannel
    trust_tier: Optional[str] = "t1"  # t0..t3
    capability_profile: Optional[str] = "execute_safe"
    tool: Optional[str] = None
    action: Optional[str] = None
    context: Optional[str] = None
    policy_decision: Literal["allow", "review", "deny"] = "allow"
    outcome: Literal["success", "error", "timeout", "rejected"] = "success"
    error_code: Optional[str] = None
    duration_ms: Optional[float] = None
    cost_usd: Optional[float] = None

class ActionDraft(BaseModel):
    id: str = Field(default_factory=lambda: f"ad_{uuid.uuid4().hex[:10]}")
    agent_id: str
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    status: Literal["pending", "approved", "rejected", "timeout"] = "pending"
    decision_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class role_profile(BaseModel): # Renamed from RoleProfile in ops_models to match schema if needed, but keeping it camelCase as in orig
    tools_allowed: Set[str] = Field(default_factory=set)
    capability: str
    trust_tier: str
    hitl_required: bool = False

class AgentInsight(BaseModel):
    id: str = Field(default_factory=lambda: f"ins_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: Literal["CONFIG_ADJUSTMENT", "POLICY_DEGRADATION", "POLICY_ADJUSTMENT", "SECURITY_ALERT"]
    priority: Literal["low", "medium", "high", "critical"]
    message: str
    recommendation: str
    agent_id: Optional[str] = None
    tool: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
