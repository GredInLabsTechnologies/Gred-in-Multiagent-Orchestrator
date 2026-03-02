import { create } from 'zustand';
import { Node, Edge, MarkerType } from 'reactflow';

/* ── Types ──────────────────────────────────────────── */

export const NODE_TYPES = ['orchestrator', 'worker', 'reviewer', 'researcher', 'tool', 'human_gate'] as const;
export type AgentNodeType = (typeof NODE_TYPES)[number];

export const ROLE_TEMPLATES: Record<string, string> = {
    orchestrator: 'Eres el orquestador principal. Descompon objetivos, delega a workers y consolida resultados finales con criterios de calidad.',
    worker: 'Eres worker de ejecucion. Implementa tareas concretas con precision y reporta resultado accionable.',
    reviewer: 'Eres reviewer. Evalua outputs de otros nodos, detecta fallos y propone correcciones especificas.',
    researcher: 'Eres researcher. Investiga fuentes relevantes, compara opciones y sintetiza hallazgos fiables.',
    tool: 'Eres nodo de herramientas. Ejecuta operaciones tecnicas y devuelve evidencia verificable.',
    human_gate: 'Eres compuerta humana. Pide confirmacion antes de continuar y valida criterios de aceptacion.',
};

export interface ProgressStats {
    done: number;
    total: number;
    percent: number;
}

export interface DraftInfo {
    draftId: string;
    prompt: string;
}

/* ── Store ──────────────────────────────────────────── */

interface GraphState {
    /* Mode */
    isEditMode: boolean;
    selectedEditNodeId: string | null;
    planName: string;
    planDescription: string;
    activePlanId: string | null;
    isExecuting: boolean;
    isSaving: boolean;

    /* Tracking */
    userPositions: Record<string, { x: number; y: number }>;
    prevNodeIds: string;
    hasFitView: boolean;

    /* Actions */
    setEditMode: (on: boolean) => void;
    setSelectedEditNodeId: (id: string | null) => void;
    setPlanName: (name: string) => void;
    setPlanDescription: (desc: string) => void;
    setActivePlanId: (id: string | null) => void;
    setIsExecuting: (v: boolean) => void;
    setIsSaving: (v: boolean) => void;
    setHasFitView: (v: boolean) => void;
    trackPosition: (id: string, pos: { x: number; y: number }) => void;
    resetPositions: () => void;
    setPrevNodeIds: (ids: string) => void;
}

export const useGraphStore = create<GraphState>((set) => ({
    isEditMode: false,
    selectedEditNodeId: null,
    planName: 'Manual Unified Plan',
    planDescription: '',
    activePlanId: null,
    isExecuting: false,
    isSaving: false,
    userPositions: {},
    prevNodeIds: '',
    hasFitView: false,

    setEditMode: (on) => set({ isEditMode: on, selectedEditNodeId: null }),
    setSelectedEditNodeId: (id) => set({ selectedEditNodeId: id }),
    setPlanName: (name) => set({ planName: name }),
    setPlanDescription: (desc) => set({ planDescription: desc }),
    setActivePlanId: (id) => set({ activePlanId: id }),
    setIsExecuting: (v) => set({ isExecuting: v }),
    setIsSaving: (v) => set({ isSaving: v }),
    setHasFitView: (v) => set({ hasFitView: v }),
    trackPosition: (id, pos) =>
        set((s) => ({ userPositions: { ...s.userPositions, [id]: pos } })),
    resetPositions: () => set({ userPositions: {}, hasFitView: false }),
    setPrevNodeIds: (ids) => set({ prevNodeIds: ids }),
}));

/* ── Helpers ────────────────────────────────────────── */

export function normalizeServerNodes(
    rawNodes: any[],
    userPositions: Record<string, { x: number; y: number }>,
): Node[] {
    return rawNodes.map((n: any) => {
        const userPos = userPositions[n.id];
        const serverType = n.type || 'custom';
        const inferredNodeType =
            n.data?.node_type ||
            (serverType === 'bridge'
                ? 'orchestrator'
                : serverType === 'orchestrator'
                    ? 'orchestrator'
                    : 'worker');
        const inferredRole = n.data?.role || inferredNodeType;
        return {
            ...n,
            type: 'custom',
            position: userPos || n.position,
            data: {
                ...n.data,
                label: n.data?.label || n.id,
                status: n.data?.status || 'pending',
                node_type: inferredNodeType,
                role: inferredRole,
                model: n.data?.model || n.data?.agent_config?.model || 'auto',
                provider: n.data?.provider || 'auto',
                prompt: n.data?.prompt || n.data?.task_description || '',
                role_definition: n.data?.role_definition || '',
                is_orchestrator: inferredNodeType === 'orchestrator',
                confidence: n.data?.confidence,
                pendingQuestions: n.data?.pendingQuestions,
                plan: n.data?.plan,
                quality: n.data?.quality,
                trustLevel: n.data?.trustLevel || 'autonomous',
            },
        };
    });
}

export function normalizeServerEdges(rawEdges: any[]): Edge[] {
    return rawEdges.map((e: any) => ({
        ...e,
        type: 'animated',
        animated: true,
        style: {
            stroke:
                e.style?.stroke ||
                (e.source === 'tunnel' ? 'var(--status-running)' : 'var(--status-done)'),
            strokeWidth: e.style?.strokeWidth || 2,
        },
        markerEnd: {
            type: MarkerType.ArrowClosed,
            color:
                e.style?.stroke ||
                (e.source === 'tunnel' ? 'var(--status-running)' : 'var(--status-done)'),
        },
    }));
}

export function toEditableNode(node: any): Node {
    return {
        ...node,
        type: 'custom',
        data: {
            ...node.data,
            node_type: node.data?.node_type || 'worker',
            role: node.data?.role || node.data?.node_type || 'worker',
            role_definition: node.data?.role_definition || '',
            prompt: node.data?.prompt || '',
            model: node.data?.model || 'auto',
            provider: node.data?.provider || 'auto',
            is_orchestrator:
                node.data?.is_orchestrator || node.data?.node_type === 'orchestrator',
            status: node.data?.status || 'pending',
        },
    };
}

export function extractDraftInfo(nodes: Node[]): DraftInfo | null {
    const firstNode = nodes.find((n) => n.data?.plan?.draft_id);
    if (!firstNode) return null;
    const draftId = firstNode.data.plan.draft_id as string;
    if (draftId.startsWith('r_')) return null;
    const allDone = nodes.every((n) => n.data?.status === 'done');
    if (allDone) return null;
    return {
        draftId,
        prompt: firstNode.data.task_description || firstNode.data.label || '',
    };
}

export function computeProgress(nodes: Node[], hasRunning: boolean): ProgressStats | null {
    const total = nodes.length;
    if (total === 0) return null;

    const terminalStatuses = ['done', 'failed', 'error', 'doubt', 'skipped'];
    const doneCount = nodes.filter((n) => terminalStatuses.includes(n.data?.status)).length;
    const hasStarted = doneCount > 0 || hasRunning;

    // Show bar only if execution has started (at least one node running or finished)
    if (!hasStarted) return null;

    return { done: doneCount, total, percent: Math.round((doneCount / total) * 100) };
}

/** Validate graph before saving: returns error message or null */
export function validateGraph(nodes: Node[], edges: Edge[]): string | null {
    if (nodes.length === 0) return 'No hay nodos para guardar en borrador manual';

    const rootCount = nodes.filter(
        (n: any) => n?.data?.is_orchestrator || n?.data?.node_type === 'orchestrator',
    ).length;
    if (rootCount !== 1) return 'Debes definir exactamente 1 nodo orquestador madre.';

    const nodeIds = new Set(nodes.map((n) => n.id));
    for (const e of edges) {
        if (!nodeIds.has(e.source) || !nodeIds.has(e.target))
            return 'Hay conexiones invalidas entre nodos.';
    }

    // Cycle detection
    const adj = new Map<string, string[]>();
    nodes.forEach((n) => adj.set(n.id, []));
    edges.forEach((e) => adj.get(e.source)?.push(e.target));
    const visited = new Set<string>();
    const stack = new Set<string>();
    const hasCycle = (id: string): boolean => {
        visited.add(id);
        stack.add(id);
        for (const nxt of adj.get(id) || []) {
            if (!visited.has(nxt) && hasCycle(nxt)) return true;
            if (stack.has(nxt)) return true;
        }
        stack.delete(id);
        return false;
    };
    for (const n of nodes) {
        if (!visited.has(n.id) && hasCycle(n.id))
            return 'El grafo contiene ciclos. Rompe el ciclo para guardar.';
    }

    return null;
}

export function buildPlanPayload(
    nodes: Node[],
    edges: Edge[],
    planName: string,
    planDescription: string,
) {
    return {
        name: planName,
        description: planDescription,
        nodes: nodes.map((n: any) => ({
            id: n.id,
            label: n.data?.label || n.id,
            prompt: n.data?.prompt || '',
            model: n.data?.model || 'auto',
            provider: n.data?.provider || 'auto',
            role: n.data?.role || 'worker',
            node_type: n.data?.node_type || 'worker',
            role_definition: n.data?.role_definition || '',
            is_orchestrator: Boolean(
                n.data?.is_orchestrator || n.data?.node_type === 'orchestrator',
            ),
            status: n.data?.status || 'pending',
            position: n.position,
            depends_on: edges
                .filter((e: any) => e.target === n.id)
                .map((e: any) => e.source),
            config: {},
        })),
        edges: edges.map((e: any) => ({
            id: e.id || `e-${e.source}-${e.target}`,
            source: e.source,
            target: e.target,
        })),
    };
}
