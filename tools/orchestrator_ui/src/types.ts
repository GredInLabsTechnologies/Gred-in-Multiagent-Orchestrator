export interface AnalysisResult {
    evaluation: string;
    artifacts: string;
    suggestions: string[];
}

export interface IslandProgress {
    island: 'sentry' | 'chromesthesia' | 'forge' | 'local' | 'ghost';
    status: string;
    percent: number;
    prompt_id?: string;
}

export interface Message {
    id: string;
    type: 'user' | 'ai';
    text: string;
    image?: string;
    timestamp: Date;
    analysis?: AnalysisResult;
    imagePath?: string;
    evolutionSuggestions?: string[];
}

export interface Backend {
    id: string;
    name: string;
    display_name: string;
    model_id: string;
    status?: 'running' | 'stopped' | 'loading' | 'error';
}

export interface EngineStatus {
    ready: boolean;
    engine: string;
    nodes: { ok: boolean; missing: string[]; error?: string };
    models: { ok: boolean; missing: string[] };
    vram: {
        total_mb: number;
        used_mb: number;
        free_mb: number;
        status: string;
    };
    manager: {
        status: 'OFFLINE' | 'BOOTING' | 'ONLINE' | 'STOPPING' | 'ERROR' | 'CONFLICT';
        backend: string | null;
        error: string | null;
        conflict?: {
            requested: string;
            active: string;
        };
    };
}

export interface StylePreset {
    id: string;
    name: string;
    description?: string;
    prompt_modifier?: string; // Used in App.tsx
}

export interface QualityMetric {
    name: string;
    status: boolean;
    score: number;
    threshold: number;
    message: string;
}

export interface WorkflowField {
    id: string;
    label: string;
    type: 'string' | 'number' | 'enum' | 'boolean';
    default: string | number | boolean | unknown;
    constraints?: {
        min?: number;
        max?: number;
        step?: number;
        options?: string[];
    };
    bind: { node_id: string; input: string };
    [key: string]: unknown;
}

// Type Guards for Rule Agent (Boundary Validation)
export function isStylePreset(item: unknown): item is StylePreset {
    if (typeof item !== 'object' || item === null) return false;
    const p = item as Record<string, unknown>;
    return typeof p.id === 'string' && typeof p.name === 'string';
}

export function isStylePresetArray(items: unknown): items is StylePreset[] {
    return Array.isArray(items) && items.every(isStylePreset);
}

export interface WorkflowGroup {
    name: string;
    fields: WorkflowField[];
}

export interface WorkflowSchema {
    id: string;
    groups: WorkflowGroup[];
}

export const API_BASE = `http://${window.location.hostname}:8001`;
