from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

ProviderType = Literal[
    "ollama_local", "ollama", "sglang", "lm_studio", "vllm", "llama-cpp", "tgi",
    "openai", "anthropic", "google", "mistral", "cohere", "deepseek", "qwen",
    "moonshot", "zai", "minimax", "baidu", "tencent", "bytedance", "iflytek",
    "01-ai", "codex", "claude", "groq", "openrouter", "together", "fireworks",
    "replicate", "huggingface", "azure-openai", "aws-bedrock", "vertex-ai",
    "custom_openai_compatible",
]

class ProviderEntry(BaseModel):
    type: str = "custom_openai_compatible"
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

class ProviderRoleBinding(BaseModel):
    provider_id: str
    model: str

class ProviderRolesConfig(BaseModel):
    orchestrator: ProviderRoleBinding
    workers: List[ProviderRoleBinding] = Field(default_factory=list)

class NormalizedModelInfo(BaseModel):
    id: str
    label: str
    context_window: Optional[int] = None
    size: Optional[str] = None
    installed: bool = False
    downloadable: bool = False
    quality_tier: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    weakness: Optional[str] = None

class ProviderModelsCatalogResponse(BaseModel):
    provider_type: ProviderType
    installed_models: List[NormalizedModelInfo] = Field(default_factory=list)
    available_models: List[NormalizedModelInfo] = Field(default_factory=list)
    recommended_models: List[NormalizedModelInfo] = Field(default_factory=list)
    can_install: bool = False
    install_method: Literal["api", "command", "manual"] = "manual"
    auth_modes_supported: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class McpServerConfig(BaseModel):
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

class ProviderConfig(BaseModel):
    schema_version: int = 2
    active: str
    providers: Dict[str, ProviderEntry]
    mcp_servers: Dict[str, McpServerConfig] = Field(default_factory=dict)
    provider_type: Optional[ProviderType] = None
    model_id: Optional[str] = None
    auth_mode: Optional[str] = None
    auth_ref: Optional[str] = None
    last_validated_at: Optional[str] = None
    effective_state: Dict[str, Any] = Field(default_factory=dict)
    capabilities_snapshot: Dict[str, Any] = Field(default_factory=dict)
    roles: Optional[ProviderRolesConfig] = None
    orchestrator_provider: Optional[str] = None
    worker_provider: Optional[str] = None
    orchestrator_model: Optional[str] = None
    worker_model: Optional[str] = None


class ProviderValidateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    org: Optional[str] = None
    account: Optional[str] = None


class ProviderValidateResponse(BaseModel):
    valid: bool
    health: Literal["ok", "degraded", "down"] = "down"
    effective_model: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error_actionable: Optional[str] = None


class ProviderModelInstallRequest(BaseModel):
    model_id: str


class ProviderModelInstallResponse(BaseModel):
    status: Literal["queued", "running", "done", "error"]
    message: str
    progress: Optional[float] = None
    job_id: Optional[str] = None


class ToolEntry(BaseModel):
    """Tool registry entry for the allowlist (fail-closed on unknown tools)."""
    name: str
    description: str = ""
    risk: Literal["read", "write", "destructive"] = "read"
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float = 0.0
    requires_hitl: bool = True
    allowed_roles: List[str] = Field(default_factory=lambda: ["admin"])
    metadata: Dict[str, Any] = Field(default_factory=dict)
    discovered: bool = False


CliDependencyStatus = Literal["pending", "running", "done", "error"]


class CliDependencyInstallRequest(BaseModel):
    dependency_id: str


class CliDependencyInstallResponse(BaseModel):
    dependency_id: str
    job_id: str
    status: CliDependencyStatus
    message: str
    progress: Optional[float] = None
    logs: List[str] = Field(default_factory=list)
