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
    model: str = Field(
        default="gpt-4o-mini",
        description="Configured default/active model for this provider entry. Provider identity remains separate.",
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Canonical identifier for the configured default/active model exposed by this provider entry.",
    )
    capabilities: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_model_fields(self) -> "ProviderEntry":
        if self.model_id and (not self.model or self.model == "gpt-4o-mini"):
            self.model = self.model_id
        if not self.model_id:
            self.model_id = self.model
        return self

    def configured_model_id(self) -> str:
        return str(self.model_id or self.model or "").strip()

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
    roles: Optional[ProviderRolesConfig] = Field(
        default=None,
        description="Canonical provider/model topology for active agents. Prefer this over legacy compatibility fields.",
    )
    orchestrator_provider: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field derived from roles.orchestrator.provider_id when roles are present.",
    )
    worker_provider: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field derived from the first roles.workers entry when roles are present.",
    )
    orchestrator_model: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field derived from roles.orchestrator.model when roles are present.",
    )
    worker_model: Optional[str] = Field(
        default=None,
        description="Deprecated compatibility field derived from the first roles.workers model when roles are present.",
    )

    @model_validator(mode="after")
    def _sync_legacy_role_fields(self) -> "ProviderConfig":
        if not self.roles:
            return self

        self.orchestrator_provider = self.roles.orchestrator.provider_id
        self.orchestrator_model = self.roles.orchestrator.model
        if self.roles.workers:
            first_worker = self.roles.workers[0]
            self.worker_provider = first_worker.provider_id
            self.worker_model = first_worker.model
        else:
            self.worker_provider = None
            self.worker_model = None
        return self

    def primary_orchestrator_binding(self) -> ProviderRoleBinding | None:
        return self.roles.orchestrator if self.roles else None

    def primary_worker_binding(self) -> ProviderRoleBinding | None:
        if not self.roles or not self.roles.workers:
            return None
        return self.roles.workers[0]


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


class ProviderSelectionRequest(BaseModel):
    provider_id: str
    model: Optional[str] = None
    prefer_family: Optional[str] = None
    api_key: Optional[str] = None


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


class CliDependencyInfo(BaseModel):
    """Info about a CLI dependency (binary) used by a provider."""
    id: str
    provider_type: str = ""
    binary: str = ""
    installed: bool = False
    version: Optional[str] = None
    installable: bool = True
    install_method: str = "npm"
    install_command: str = ""
    message: str = ""


class CliDependencyInstallRequest(BaseModel):
    dependency_id: str


class CliDependencyInstallResponse(BaseModel):
    dependency_id: str
    job_id: str
    status: CliDependencyStatus
    message: str
    progress: Optional[float] = None
    logs: List[str] = Field(default_factory=list)
