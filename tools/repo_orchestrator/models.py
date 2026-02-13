from __future__ import annotations

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass

class AgentQuality(BaseModel):
    score: int
    alerts: List[str]
    lastCheck: str

class AgentPlan(BaseModel):
    id: str
    steps: List[Dict[str, str]]
    status: str

class NodeData(BaseModel):
    label: str
    status: Optional[str] = "active"
    path: Optional[str] = None
    plan: Optional[AgentPlan] = None
    trustLevel: Optional[str] = None
    quality: Optional[AgentQuality] = None
    subAgents: Optional[List[SubAgent]] = None

class GraphNode(BaseModel):
    id: str
    type: str
    data: NodeData
    position: Dict[str, float]

class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    animated: bool = False

class GraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
class RepoEntry(BaseModel):
    name: str
    path: str

class VitaminizeResponse(BaseModel):
    status: str
    created_files: List[str]
    active_repo: Optional[str] = None

class StatusResponse(BaseModel):
    version: str
    uptime_seconds: float

class UiStatusResponse(BaseModel):
    version: str
    uptime_seconds: float
    allowlist_count: int
    last_audit_line: Optional[str] = None
    service_status: str

class FileWriteRequest(BaseModel):
    path: str
    content: str

class PlanTask(BaseModel):
    id: str
    title: str
    description: str
    status: Literal['pending', 'running', 'done', 'failed']
    dependencies: List[str]

class AgentAssignment(BaseModel):
    agentId: str
    taskIds: List[str]

class Plan(BaseModel):
    id: str
    title: str
    status: Literal['draft', 'review', 'approved', 'executing', 'completed', 'failed']
    tasks: List[PlanTask]
    assignments: List[AgentAssignment]

class PlanCreateRequest(BaseModel):
    title: str
    task_description: str

class PlanUpdateRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[Literal['draft', 'review', 'approved', 'executing', 'completed', 'failed']] = None

class AgentMessage(BaseModel):
    id: str
    from_role: Literal['agent', 'orchestrator', 'user'] = Field(alias="from", default=None)
    agentId: str
    type: Literal['question', 'instruction', 'report', 'reassignment']
    content: str
    timestamp: str

    model_config = {"populate_by_name": True}

    def model_dump(self, **kwargs):
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)

    def dict(self, **kwargs):
        kwargs.setdefault("by_alias", True)
        return super().dict(**kwargs)

class SubAgentConfig(BaseModel):
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048

class SubAgent(BaseModel):
    id: str
    parentId: str
    name: str
    model: str
    status: Literal['starting', 'working', 'idle', 'terminated', 'failed']
    currentTask: Optional[str] = None
    config: SubAgentConfig
    result: Optional[str] = None

class DelegationRequest(BaseModel):
    subTaskDescription: str
    modelPreference: str = "llama3"
    constraints: Dict[str, Any] = {}

class BatchDelegationRequest(BaseModel):
    tasks: List[DelegationRequest]


# --- Phase 11: Hybrid Provider System ---

class ProviderType(BaseModel):
    """Supported provider backends."""
    # Using a model instead of enum for JSON serialization simplicity
    pass

PROVIDER_TYPES = ["ollama", "groq", "openrouter", "codex", "custom"]

class ProviderConfig(BaseModel):
    """User-configurable provider connection."""
    id: str
    type: Literal["ollama", "groq", "openrouter", "codex", "custom"]
    name: str
    enabled: bool = True
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    is_local: bool = False
    max_concurrent: int = 4
    cost_per_1k_tokens: float = 0.0  # USD
    max_context: int = 4096
    models: List[str] = []  # Available models for this provider

class ComputeNode(BaseModel):
    """Physical hardware node in the hybrid architecture."""
    id: str
    name: str
    role: str  # e.g. "Mobile Edge Node", "Heavy Compute Node"
    max_concurrent_agents: int
    current_agents: int = 0
    preferred_models: List[str] = []
    provider_ids: List[str] = []  # Which providers run on this node
    constraints: Dict[str, Any] = {}  # thermal_limit, vram_limit, etc.

class TaskClassification(BaseModel):
    """How GIMO classifies a task for routing."""
    task_type: Literal["code_monkey", "architect"]
    complexity: Literal["low", "medium", "high"]
    preferred_provider_type: Literal["local", "cloud"]
    reason: str

class ProviderHealth(BaseModel):
    """Health status of a provider."""
    provider_id: str
    available: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    last_check: str

class ProviderCreateRequest(BaseModel):
    type: Literal["ollama", "groq", "openrouter", "codex", "custom"]
    name: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    is_local: bool = False
    max_concurrent: int = 4
    models: List[str] = []

