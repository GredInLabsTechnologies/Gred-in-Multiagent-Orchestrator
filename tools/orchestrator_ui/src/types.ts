export const API_BASE = import.meta.env.VITE_API_URL || `http://${globalThis.location?.hostname ?? 'localhost'}:9325`;

export type TrustLevel = 'autonomous' | 'supervised' | 'restricted';

export interface ConfidenceScore {
    score: number;
    percentage: string;
    level: string;
    reason: string;
}

export interface GraphNode {
    id: string;
    type: string;
    data: {
        label: string;
        status?: string;
        path?: string;
        plan?: AgentPlan;
        trustLevel?: TrustLevel;
        pendingQuestions?: AgentQuestion[];
        quality?: QualityMetrics;
        subAgents?: SubAgent[];
        // Disruptive Observatory Fields
        system_prompt?: string;
        agent_config?: {
            model: string;
            role: string;
            goal: string;
            backstory?: string;
        };
        task_description?: string;
        depends_on?: string[];
        estimated_tokens?: number;
        editable?: boolean;
    };
    position: { x: number; y: number };
}

export type DegradationFlag = 'repetition' | 'coherence' | 'relevance' | 'latency' | 'none';

export interface QualityMetrics {
    score: number; // 0-100
    alerts: DegradationFlag[];
    lastCheck: string;
}

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed';

export interface AgentQuestion {
    id: string;
    question: string;
    context?: string;
    timestamp: string;
    status: 'pending' | 'answered' | 'dismissed';
}

export interface AgentTask {
    id: string;
    description: string;
    status: TaskStatus;
    output?: string;
    tokens_used?: number;
    cost_usd?: number;
    confidence?: ConfidenceScore;
}

export interface AgentThought {
    id: string;
    content: string;
}

export interface AgentPlan {
    id: string;
    draft_id?: string;
    tasks: AgentTask[];
    currentStep?: number;
    reasoning?: AgentThought[];
    confidence?: ConfidenceScore;
}

export interface GraphEdge {
    id: string;
    source: string;
    target: string;
    animated?: boolean;
}

export interface GraphResponse {
    nodes: GraphNode[];
    edges: GraphEdge[];
}

export interface UiStatusResponse {
    version: string;
    uptime_seconds: number;
    allowlist_count: number;
    last_audit_line: string | null;
    service_status: string;
}

export interface LicenseInfo {
    plan: 'standard' | 'admin' | 'none';
    status: 'active' | 'expired' | 'suspended' | 'none';
    isLifetime: boolean;
    keyPreview: string;
    installationsUsed: number;
    installationsMax: number;
    expiresAt: string | null;
}

export interface SubscriptionInfo {
    status: 'active' | 'canceled' | 'past_due' | 'none';
    currentPeriodEnd: string | null;
    cancelAtPeriodEnd: boolean;
}

export interface SessionInfo {
    role: string;
    uid: string;
    email: string;
    displayName: string;
    plan: string;
    firebaseUser: boolean;
    createdAt: number;
    lastSeen: number;
    ttlSeconds: number;
    expiresInSeconds: number;
}

export interface UserProfile {
    user: {
        uid?: string;
        role: string;
        email: string;
        displayName: string;
        photoURL?: string;
    };
    license: LicenseInfo;
    subscription: SubscriptionInfo;
    session: SessionInfo;
    profileSource?: 'upstream' | 'session_cache';
}

export type PlanStatus = 'draft' | 'review' | 'approved' | 'executing' | 'completed' | 'failed';

export interface PlanTask {
    id: string;
    title: string;
    description: string;
    status: TaskStatus;
    dependencies: string[]; // IDs of other PlanTasks
}

export interface AgentAssignment {
    agentId: string;
    taskIds: string[];
}

export interface Plan {
    id: string;
    title: string;
    status: PlanStatus;
    tasks: PlanTask[];
    assignments: AgentAssignment[];
}

export interface PlanCreateRequest {
    title: string;
    task_description: string;
}

export type MessageType = 'question' | 'instruction' | 'report' | 'reassignment';

export interface AgentMessage {
    id: string;
    from: 'agent' | 'orchestrator' | 'user';
    agentId: string;
    type: MessageType;
    content: string;
    timestamp: string;
}

export interface SubAgentConfig {
    model: string;
    temperature: number;
    max_tokens: number;
}

export interface SubAgent {
    id: string;
    parentId: string;
    name: string;
    model: string;
    status: 'starting' | 'working' | 'idle' | 'terminated' | 'failed';
    currentTask?: string;
    config: SubAgentConfig;
    result?: string;
}

export interface DelegationRequest {
    subTaskDescription: string;
    modelPreference: string;
    constraints?: Record<string, any>;
}

// --- Phase 11: Hybrid Provider System ---

export type ProviderType =
    | 'ollama'
    | 'groq'
    | 'openrouter'
    | 'codex'
    | 'custom'
    | 'ollama_local'
    | 'openai'
    | 'custom_openai_compatible';

export interface ProviderConfig {
    id: string;
    type: ProviderType;
    name: string;
    enabled: boolean;
    base_url?: string;
    api_key?: string;
    default_model?: string;
    is_local: boolean;
    max_concurrent: number;
    cost_per_1k_tokens: number;
    max_context: number;
    models: string[];
}

export interface ComputeNode {
    id: string;
    name: string;
    role: string;
    max_concurrent_agents: number;
    current_agents: number;
    preferred_models: string[];
    provider_ids: string[];
    constraints: Record<string, any>;
}

export interface ProviderHealth {
    provider_id: string;
    available: boolean;
    latency_ms?: number;
    error?: string;
    last_check: string;
}

export interface ProviderCreateRequest {
    type: ProviderType;
    name: string;
    base_url?: string;
    api_key?: string;
    default_model?: string;
    is_local?: boolean;
    max_concurrent?: number;
    models?: string[];
}

export interface ProviderInfo {
    id: string;
    type: string;
    is_local: boolean;
    config: any;
    capabilities?: Record<string, any>;
    model?: string;
    auth_mode?: string | null;
    auth_ref?: string | null;
}

export interface ProviderModelInfo {
    id: string;
    label: string;
    installed: boolean;
    downloadable: boolean;
    context_window?: number;
    size?: string;
    quality_tier?: string;
    description?: string;
    capabilities?: string[];
    weakness?: string;
}

export interface ProviderCatalogResponse {
    provider_type: string;
    installed_models: ProviderModelInfo[];
    available_models: ProviderModelInfo[];
    recommended_models: ProviderModelInfo[];
    can_install: boolean;
    install_method: 'api' | 'command' | 'manual';
    auth_modes_supported: string[];
    warnings: string[];
}

export interface ProviderValidatePayload {
    api_key?: string;
    base_url?: string;
    org?: string;
    account?: string;
}

export interface ProviderValidateResult {
    valid: boolean;
    health: string;
    effective_model?: string;
    warnings: string[];
    error_actionable?: string;
}

export interface ProviderInstallResult {
    status: 'queued' | 'running' | 'done' | 'error';
    message: string;
    progress?: number;
    job_id?: string;
}

export interface CliDependencyStatus {
    id: string;
    provider_type: string;
    binary: string;
    installed: boolean;
    version?: string | null;
    installable: boolean;
    install_method: 'npm' | 'manual';
    install_command?: string | null;
    message?: string | null;
}

export interface CliDependencyInstallResult {
    status: 'queued' | 'running' | 'done' | 'error';
    message: string;
    dependency_id: string;
    progress?: number;
    job_id?: string;
    logs?: string[];
}

export interface SaveActiveProviderPayload {
    providerId: string;
    providerType: string;
    modelId: string;
    authMode: string;
    roleTarget?: 'orchestrator' | 'worker';
    apiKey?: string;
    account?: string;
    baseUrl?: string;
    org?: string;
}

export interface ProviderRoleBinding {
    provider_id: string;
    model: string;
}

export interface ProviderRolesConfig {
    orchestrator: ProviderRoleBinding;
    workers: ProviderRoleBinding[];
}

export interface RepoInfo {
    name: string;
    path: string;
}

export interface OpsTask {
    id: string;
    title: string;
    scope: string;
    depends: string[];
    status: 'pending' | 'in_progress' | 'done' | 'blocked';
    description: string;
}

export interface OpsPlan {
    id: string;
    workspace: string;
    created: string;
    title: string;
    objective: string;
    tasks: OpsTask[];
    constraints: string[];
}

export interface OpsDraft {
    id: string;
    prompt: string;
    context?: {
        detected_intent?: string;
        decision_path?: 'security_block' | 'direct_response' | 'llm_generate';
        intent_declared?: string;
        intent_effective?: string;
        risk_score?: number;
        decision_reason?: string;
        execution_decision?:
        | 'AUTO_RUN_ELIGIBLE'
        | 'HUMAN_APPROVAL_REQUIRED'
        | 'RISK_SCORE_TOO_HIGH'
        | 'DRAFT_REJECTED_FORBIDDEN_SCOPE';
        can_bypass_llm?: boolean;
        error_actionable?: string;
        [key: string]: unknown;
    };
    provider?: string | null;
    content?: string | null;
    status: 'draft' | 'rejected' | 'approved' | 'error';
    error?: string | null;
    created_at: string;
}

export type ChatExecutionStepKey =
    | 'intent_detected'
    | 'draft_created'
    | 'approved'
    | 'run_created'
    | 'run_status';

export type ChatExecutionStepStatus = 'pending' | 'done' | 'error';

export interface ChatExecutionStep {
    key: ChatExecutionStepKey;
    label: string;
    status: ChatExecutionStepStatus;
    detail?: string;
}

export interface OpsApproved {
    id: string;
    draft_id: string;
    prompt: string;
    provider?: string | null;
    content: string;
    approved_at: string;
    approved_by?: string | null;
}

export interface OpsRun {
    id: string;
    approved_id: string;
    status: 'pending' | 'running' | 'done' | 'error' | 'cancelled';
    log: Array<{ ts: string; level: string; msg: string }>;
    started_at?: string | null;
    created_at: string;
}

export interface OpsApproveResponse {
    approved: OpsApproved;
    run: OpsRun | null;
}

export interface OpsConfig {
    default_auto_run: boolean;
    draft_cleanup_ttl_days: number;
    max_concurrent_runs: number;
    operator_can_generate: boolean;
    ui_show_ids_events: boolean;
    ui_enable_chat_investigation: boolean;
}

export type AgentRole = 'orchestrator' | 'worker' | 'external_action';
export type AgentChannel = 'cli' | 'provider_api' | 'gpt_actions' | 'mcp_remote';
export type PolicyDecision = 'allow' | 'review' | 'deny';
export type AgentOutcome = 'success' | 'error' | 'timeout' | 'rejected';

export interface AgentActionEvent {
    timestamp: string;
    agent_id: string;
    agent_role: AgentRole;
    channel: AgentChannel;
    trust_tier?: string;
    capability_profile?: string;
    tool?: string;
    action?: string;
    context?: string;
    policy_decision: PolicyDecision;
    outcome: AgentOutcome;
    error_code?: string;
    duration_ms?: number;
    cost_usd?: number;
}

export interface AgentInsight {
    type: 'CONFIG_ADJUSTMENT' | 'POLICY_DEGRADATION' | 'POLICY_ADJUSTMENT';
    priority: 'high' | 'medium' | 'low';
    message: string;
    recommendation: string;
}

export interface ProviderEntry {
    type: 'openai_compat' | 'anthropic' | 'gemini';
    base_url?: string | null;
    api_key?: string | null;
    model: string;
}

export interface RemoteProviderConfig {
    active: string;
    providers: Record<string, ProviderEntry>;
}

export interface EvalCase {
    case_id?: string;
    input_state: Record<string, any>;
    expected_state: Record<string, any>;
    threshold?: number;
}

export interface EvalDataset {
    id?: number;
    workflow_id: string;
    name: string;
    description?: string;
    cases: EvalCase[];
    created_at?: string;
    version?: string;
    dataset_id?: number; // Virtual ID from list_eval_datasets fallback
    version_tag?: string;
}

export interface EvalRunRequest {
    workflow_id: string;
    dataset_id?: number;
    dataset?: EvalDataset;
    judge: string;
    gate?: string;
    case_limit?: number;
}

export interface EvalCaseResult {
    case_id: string;
    passed: boolean;
    score: number;
    input_state: Record<string, any>;
    expected_state: Record<string, any>;
    actual_state: Record<string, any>;
    reason?: string;
}

export interface EvalRunReport {
    eval_run_id?: number;
    workflow_id: string;
    dataset_id: number;
    total_cases: number;
    passed_cases: number;
    pass_rate: number;
    gate_passed: boolean;
    average_score: number;
    details: EvalCaseResult[];
    created_at?: string;
}

export interface EvalRunSummary {
    run_id: number;
    workflow_id: string;
    gate_passed: boolean;
    pass_rate: number;
    avg_score: number;
    total_cases: number;
    passed_cases: number;
    failed_cases: number;
    created_at: string;
    dataset_id?: number;
}

export interface EvalRunDetail {
    run_id: number;
    workflow_id: string;
    created_at: string;
    report: EvalRunReport;
}

// --- Phase 3.2: Observability ---

export interface Span {
    trace_id: string;
    span_id: string;
    parent_id?: string | null;
    name: string;
    start_time: string;
    end_time?: string | null;
    status: 'ok' | 'error';
    attributes: Record<string, any>;
    events: Array<{ name: string; timestamp: string; attributes?: Record<string, any> }>;
}

export interface Trace {
    trace_id: string;
    root_span: Span;
    spans: Span[];
    start_time: string;
    end_time?: string | null;
    duration_ms?: number;
    status: 'ok' | 'error' | 'pending';
    workflow_id?: string;
}

export interface ObservabilityMetrics {
    total_workflows: number;
    active_workflows: number;
    total_tokens: number;
    estimated_cost: number;
    error_rate: number;
    avg_latency_ms: number;
    fallback_rate?: number;
    human_approval_required_rate?: number;
    policy_block_rate?: number;
    latency_ms_by_stage?: Record<string, number>;
    errors_by_category?: Record<string, number>;
}

// --- Phase 10: Token Mastery ---

export interface ProviderBudget {
    provider: string;
    max_cost_usd: number | null;
    period: 'daily' | 'weekly' | 'monthly' | 'total';
}

export interface CascadeConfig {
    enabled: boolean;
    min_tier: string;
    max_tier: string;
    quality_threshold: number;
    max_escalations: number;
}

export interface EcoModeConfig {
    mode: 'off' | 'binary' | 'smart';
    floor_tier: string;
    confidence_threshold_aggressive?: number;
    confidence_threshold_moderate?: number;
}

export interface UserEconomyConfig {
    autonomy_level: 'manual' | 'advisory' | 'guided' | 'autonomous';
    global_budget_usd: number | null;
    provider_budgets: ProviderBudget[];
    alert_thresholds: number[];
    cascade: CascadeConfig;
    eco_mode: EcoModeConfig;
    allow_roi_routing: boolean;
    model_floor: string | null;
    model_ceiling: string | null;
    cache_enabled: boolean;
    cache_ttl_hours: number;
    show_cost_predictions: boolean;
}

export interface MasteryStatus {
    eco_mode_enabled: boolean;
    total_savings_usd: number;
    efficiency_score: number;
    tips: string[];
}

export interface BudgetForecast {
    scope: string; // "global" or provider name
    current_spend: number;
    limit: number | null;
    remaining: number | null;
    remaining_pct: number | null;
    burn_rate_hourly: number;
    hours_to_exhaustion: number | null;
    alert_level: 'none' | 'warning' | 'critical';
}

export interface RoiLeaderboardEntry {
    model: string;
    task_type: string;
    roi_score: number;
    avg_quality: number;
    avg_cost: number;
    sample_count: number;
}

export interface CascadeStats {
    task_type: string;
    total_calls: number;
    cascaded_calls: number;
    avg_cascade_depth: number;
    total_spent: number;
}

export interface CacheStats {
    total_calls: number;
    cache_hits: number;
    hit_rate: number;
    estimated_savings_usd: number;
}

export interface CostAnalytics {
    daily_costs: Array<{ date: string; cost: number; tokens: number }>;
    by_model: Array<{ model: string; cost: number; count: number }>;
    by_task_type: Array<{ task_type: string; cost: number; quality: number }>;
    by_provider: Array<{ provider: string; cost: number; total_tokens: number; count: number }>;
    roi_leaderboard: RoiLeaderboardEntry[];
    cascade_stats: CascadeStats[];
    cache_stats: CacheStats;
    total_savings: number;
}

export interface MasteryRecommendation {
    task_type: string;
    suggested_model: string;
    reason: string;
}
// --- Phase 5: Skills System ---

export type AgentMood = 'neutral' | 'forensic' | 'executor' | 'dialoger' | 'creative' | 'guardian' | 'mentor';

export interface Skill {
    id: string;
    name: string;
    description: string;
    command: string;
    replace_graph: boolean;
    nodes: any[];
    edges: any[];
    created_at: string;
    updated_at: string;
    version: number;
    mood: AgentMood;
    tags: string[];
    author: string;
    published: boolean;
}

export interface SkillExecuteResponse {
    skill_run_id: string;
    skill_id: string;
    replace_graph: boolean;
    status: string;
}

export interface SkillAutoGenRequest {
    prompt: string;
    name_hint?: string;
    replace_graph?: boolean;
    mood?: AgentMood;
}

export interface SkillUpdateRequest {
    name?: string;
    description?: string;
    nodes?: any[];
    edges?: any[];
    mood?: AgentMood;
    replace_graph?: boolean;
    tags?: string[];
}

export interface SkillAnalytics {
    skill_id: string;
    total_runs: number;
    successful_runs: number;
    failed_runs: number;
    success_rate: number;
    avg_duration_seconds: number;
    total_tokens_used: number;
    last_run_at: string | null;
    last_status: string | null;
}

export type SkillRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'error';

export interface SkillRun {
    id: string;
    skill_id: string;
    command: string;
    status: SkillRunStatus;
    progress: number;
    message: string;
    started_at: string;
    finished_at?: string | null;
}

export interface SkillNotificationPayload {
    skill_run_id: string;
    skill_id: string;
    command: string;
    status: SkillRunStatus;
    progress: number;
    message: string;
    started_at: string;
    finished_at?: string | null;
}
// --- Phase 6: Custom Graph Plans ---

export interface CustomPlanNode {
    id: string;
    label: string;
    prompt: string;
    model: string;
    provider: string;
    role: string;
    depends_on: string[];
    status: 'pending' | 'running' | 'done' | 'error' | 'skipped';
    output?: string;
    error?: string;
    position: { x: number; y: number };
    config: Record<string, any>;
}

export interface CustomPlanEdge {
    id: string;
    source: string;
    target: string;
}

export interface CustomPlan {
    id: string;
    name: string;
    description: string;
    nodes: CustomPlanNode[];
    edges: CustomPlanEdge[];
    status: 'draft' | 'approved' | 'running' | 'done' | 'error';
    created_at: string;
    updated_at: string;
    run_log: Array<{ ts: string; level: string; msg: string }>;
}

export interface CreateCustomPlanRequest {
    name: string;
    description: string;
    nodes: CustomPlanNode[];
    edges: CustomPlanEdge[];
}
