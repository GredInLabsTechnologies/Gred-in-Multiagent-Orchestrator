// API Configuration
export const API_BASE = import.meta.env.VITE_API_URL || `http://${globalThis.location?.hostname ?? 'localhost'}:9325`;

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
    context?: Record<string, unknown>;
    provider?: string | null;
    content?: string | null;
    status: 'draft' | 'rejected' | 'approved' | 'error';
    error?: string | null;
    created_at: string;
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
}

export interface ProviderEntry {
    type: 'openai_compat' | 'anthropic' | 'gemini';
    base_url?: string | null;
    api_key?: string | null;
    model: string;
}

export interface ProviderConfig {
    active: string;
    providers: Record<string, ProviderEntry>;
}
