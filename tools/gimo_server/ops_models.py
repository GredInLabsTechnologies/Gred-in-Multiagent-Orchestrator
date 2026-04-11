from __future__ import annotations

# Compatibility shim: Re-export everything from the new models/ directory
# This ensures existing code importing from tools.gimo_server.ops_models continues to work.

try:
    from tools.gimo_server.models import (
        OpsTask, OpsPlan, OpsDraft, OpsApproved, OpsRunStatus, OpsRun,
        OpsConfig, ExecutorReport, OpsCreateDraftRequest, OpsUpdateDraftRequest,
        OpsApproveResponse, OpsCreateRunRequest, OpsResumeRunRequest, ChildRunRequest, RepoEntry, RunEvent,
        StatusResponse, ServiceStatusResponse, UiStatusResponse, VitaminizeResponse,
        SubAgent, SubAgentConfig,
        GimoItemType, GimoItemStatus, GimoThreadStatus, GimoItem, GimoTurn, GimoThread,
        AgentRole, AgentChannel, AgentProfile, AgentActionEvent, AgentInsight,
        ActionDraft, role_profile,
        ProviderType, ProviderEntry, ProviderRoleBinding,
        ProviderRolesConfig, NormalizedModelInfo, ProviderModelsCatalogResponse,
        McpServerConfig, ProviderConfig,
        ProviderValidateRequest, ProviderValidateResponse, ProviderSelectionRequest,
        ProviderUpsertRequest, ProviderCredentialUpdateRequest,
        ProviderModelInstallRequest, ProviderModelInstallResponse,
        ToolEntry, CliDependencyStatus, CliDependencyInfo, CliDependencyInstallRequest, CliDependencyInstallResponse,
        ProviderDiagnosticEntry, ProviderDiagnosticReport,
        CircuitBreakerConfigModel, PHASE4_INTENT_CLASSES,
        ExecutionDecisionCode, IntentDecisionAudit, RuntimePolicyConfig,
        BaselineManifest, PolicyDecision, PolicyRuleMatch, PolicyRule, PolicyConfig,
        TrustRecord, TrustEvent, TrustDashboardEntry, StrategyFinalStatus,
        QualityRating, ProviderBudget,
        CascadeConfig, EcoModeConfig, UserEconomyConfig, CostEvent, BudgetForecast,
        NodeEconomyMetrics, PlanEconomySnapshot, PlanAutonomyUpdateRequest, CascadeResult,
        CostAnalytics, MasteryStatus, IntentClass,
        DelegationStatus, QaVerdict, RepoSnapshot, RepoContext, ContractExecution,
        StrictContract, Delegation, CommandRun, TestRun, DiffRef, Evidence, Failure,
        QaState, WorkflowNode, WorkflowEdge, WorkflowGraph,
        WorkflowCheckpoint, WorkflowState, WorkflowExecuteRequest, ContractCheck,
        WorkflowContract, PlanNodePosition, PlanNodeBinding, PlanNodeRoutingSummary,
        PlanNodeExecutionHints, PlanNode, PlanEdge, CustomPlan, CreatePlanRequest,
        UpdatePlanRequest, TaskRole, MoodName, ExecutionPolicyName, WorkflowPhase,
        AgentPresetName, BindingMode, TaskFingerprintParts, TaskDescriptor,
        TaskConstraints, ResolvedAgentProfile, RoutingDecisionSummary,
        RoutingDecision, ProfileSummary, EvalGoldenCase, EvalDataset, EvalJudgeConfig,
        EvalGateConfig, EvalRunRequest, EvalCaseResult, EvalRunReport,
        EvalRunSummary, EvalRunDetail,
        WebSearchProvider, WebSearchQuery, WebSearchResult, WebSearchFusionResponse,
    )
except ImportError:
    from .models import (
        role_profile,
    )

RoleProfile = role_profile
