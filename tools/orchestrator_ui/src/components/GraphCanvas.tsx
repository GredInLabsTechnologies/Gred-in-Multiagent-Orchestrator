import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import ReactFlow, {
    Background,
    Controls,
    MiniMap,
    Panel,
    useNodesState,
    useEdgesState,
    MarkerType,
    NodeMouseHandler,
    useReactFlow,
    Connection,
    addEdge,
    EdgeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { ComposerNode } from './ComposerNode';
import { PlanOverlayCard } from './PlanOverlayCard';
import { API_BASE } from '../types';
import { Edit2, Save, X, Plus, Play, Trash2, Info } from 'lucide-react';
import { useToast } from './Toast';
import { useAvailableModels } from '../hooks/useAvailableModels';

const nodeTypes = {
    custom: ComposerNode,
};

const NODE_TYPES = ['orchestrator', 'worker', 'reviewer', 'researcher', 'tool', 'human_gate'] as const;
const ROLE_DEFINITION_TEMPLATES: Record<string, string> = {
    orchestrator: 'Eres el orquestador principal. Descompón objetivos, delega a workers y consolida resultados finales con criterios de calidad.',
    worker: 'Eres worker de ejecución. Implementa tareas concretas con precisión y reporta resultado accionable.',
    reviewer: 'Eres reviewer. Evalúa outputs de otros nodos, detecta fallos y propone correcciones específicas.',
    researcher: 'Eres researcher. Investiga fuentes relevantes, compara opciones y sintetiza hallazgos fiables.',
    tool: 'Eres nodo de herramientas. Ejecuta operaciones técnicas y devuelve evidencia verificable.',
    human_gate: 'Eres compuerta humana. Pide confirmación antes de continuar y valida criterios de aceptación.',
};

interface GraphCanvasProps {
    onNodeSelect: (nodeId: string | null) => void;
    selectedNodeId: string | null;
    onNodeCountChange?: (count: number) => void;
    onApprovePlan?: (draftId: string) => void;
    onRejectPlan?: (draftId: string) => void;
    onEditPlan?: () => void;
    planLoading?: boolean;
    activePlanIdFromChat?: string | null;
}

export const GraphCanvas: React.FC<GraphCanvasProps> = ({
    onNodeSelect,
    selectedNodeId,
    onNodeCountChange,
    onApprovePlan,
    onRejectPlan,
    onEditPlan,
    planLoading,
    activePlanIdFromChat,
}) => {
    const { addToast } = useToast();
    const { models } = useAvailableModels();
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [isEditMode, setIsEditMode] = useState(false);
    const [selectedEditNodeId, setSelectedEditNodeId] = useState<string | null>(null);
    const [planName, setPlanName] = useState('Manual Unified Plan');
    const [planDescription, setPlanDescription] = useState('');
    const [activePlanId, setActivePlanId] = useState<string | null>(null);
    const [isExecuting, setIsExecuting] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const hasFitView = useRef(false);
    const userPositions = useRef<Record<string, { x: number; y: number }>>({});
    const prevNodeIds = useRef<string>('');
    const { project } = useReactFlow();

    // Track user-moved node positions
    const handleNodesChange = useCallback((changes: any[]) => {
        onNodesChange(changes);
        for (const change of changes) {
            if (change.type === 'position' && change.position) {
                userPositions.current[change.id] = { ...change.position };
            }
        }
    }, [onNodesChange]);

    // Extract draft info — only show overlay for pending drafts, not completed runs
    const draftInfo = useMemo(() => {
        const firstNode = nodes.find(n => n.data?.plan?.draft_id);
        if (!firstNode) return null;
        const draftId = firstNode.data.plan.draft_id as string;
        // Don't show plan overlay for runs (r_...) or if all nodes are done
        if (draftId.startsWith('r_')) return null;
        const allDone = nodes.every(n => n.data?.status === 'done');
        if (allDone) return null;
        return {
            draftId,
            prompt: firstNode.data.task_description || firstNode.data.label || '',
        };
    }, [nodes]);

    const fetchGraphData = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/ui/graph`, {
                credentials: 'include'
            });

            if (response.status === 401 || response.status === 403) {
                onNodeCountChange?.(-1);
                return;
            }

            if (!response.ok) {
                addToast(`Error al cargar el grafo (HTTP ${response.status})`, 'error');
                onNodeCountChange?.(0);
                return;
            }

            const data = await response.json();

            const formattedEdges = data.edges.map((e: any) => ({
                ...e,
                animated: true,
                style: {
                    stroke: e.style?.stroke || (e.source === 'tunnel' ? 'var(--status-running)' : 'var(--status-done)'),
                    strokeWidth: e.style?.strokeWidth || 2,
                },
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: e.style?.stroke || (e.source === 'tunnel' ? 'var(--status-running)' : 'var(--status-done)'),
                },
            }));

            // Normalize all server nodes to unified 'custom' type (ComposerNode)
            const nodesWithLiveState = data.nodes.map((n: any) => {
                const userPos = userPositions.current[n.id];
                const serverType = n.type || 'custom';
                const inferredNodeType = n.data?.node_type
                    || (serverType === 'bridge' ? 'orchestrator' : serverType === 'orchestrator' ? 'worker' : 'worker');
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
                    }
                };
            });

            onNodeCountChange?.(nodesWithLiveState.length);

            // Check if the node set changed (new plan / different nodes)
            const newNodeIds = nodesWithLiveState.map((n: any) => n.id).sort().join(',');
            if (newNodeIds !== prevNodeIds.current) {
                // New graph — reset positions and trigger fitView
                userPositions.current = {};
                hasFitView.current = false;
                prevNodeIds.current = newNodeIds;
            }

            setNodes(nodesWithLiveState);
            setEdges(formattedEdges);
        } catch (error) {
            addToast('Error al cargar datos del grafo', 'error');
            onNodeCountChange?.(0);
        }
    }, [setNodes, setEdges, onNodeCountChange, addToast]);

    const hasRunningNodes = useMemo(() => nodes.some(n => n.data?.status === 'running'), [nodes]);

    useEffect(() => {
        if (isEditMode) return;
        fetchGraphData();
        const intervalTime = hasRunningNodes ? 2000 : 5000;
        const interval = setInterval(fetchGraphData, intervalTime);
        return () => clearInterval(interval);
    }, [fetchGraphData, hasRunningNodes, isEditMode]);

    const progressStats = useMemo(() => {
        const actionableNodes = nodes.filter(n => n.data?.status && n.data.status !== 'pending');
        if (actionableNodes.length === 0 && !hasRunningNodes) return null;

        const total = nodes.length;
        if (total === 0) return null;
        const doneCount = nodes.filter(n => ['done', 'failed', 'error', 'doubt', 'skipped'].includes(n.data?.status)).length;

        if (!hasRunningNodes && doneCount !== total) return null;
        if (doneCount === total && !hasRunningNodes) return null;

        return { done: doneCount, total, percent: Math.round((doneCount / total) * 100) };
    }, [nodes, hasRunningNodes]);

    const toEditableNode = useCallback((node: any) => {
        // Nodes are already normalized to type 'custom' by fetchGraphData
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
                is_orchestrator: node.data?.is_orchestrator || node.data?.node_type === 'orchestrator',
                status: node.data?.status || 'pending',
            },
        };
    }, []);

    useEffect(() => {
        if (!isEditMode) {
            setSelectedEditNodeId(null);
            return;
        }

        if (nodes.length === 0) {
            const seedNode = {
                id: `node_${Date.now()}`,
                type: 'custom',
                position: { x: 220, y: 120 },
                data: {
                    label: 'Initial Task',
                    status: 'pending',
                    trustLevel: 'supervised',
                    node_type: 'orchestrator',
                    role: 'orchestrator',
                    role_definition: ROLE_DEFINITION_TEMPLATES.orchestrator,
                    model: 'auto',
                    provider: 'auto',
                    prompt: 'Define el plan y delega tareas a los workers.',
                    is_orchestrator: true,
                },
            };
            setNodes([seedNode] as any);
            setSelectedEditNodeId(seedNode.id);
            return;
        }

        setNodes((nds) => nds.map((n: any) => toEditableNode(n)));
    }, [isEditMode, setNodes, toEditableNode]);

    // Load a plan generated from chat into the graph as editable nodes
    useEffect(() => {
        if (!activePlanIdFromChat) return;

        const loadPlan = async () => {
            try {
                const res = await fetch(`${API_BASE}/ops/custom-plans/${activePlanIdFromChat}`, {
                    credentials: 'include',
                });
                if (!res.ok) return;
                const plan = await res.json();
                if (!plan.nodes || plan.nodes.length === 0) return;

                const loadedNodes = plan.nodes.map((n: any) => ({
                    id: n.id,
                    type: 'custom',
                    position: n.position || { x: 0, y: 0 },
                    data: {
                        label: n.label || n.id,
                        status: n.status || 'pending',
                        node_type: n.node_type || 'worker',
                        role: n.role || n.node_type || 'worker',
                        model: n.model || 'auto',
                        provider: n.provider || 'auto',
                        prompt: n.prompt || '',
                        role_definition: n.role_definition || '',
                        is_orchestrator: n.is_orchestrator || n.node_type === 'orchestrator',
                        trustLevel: 'supervised',
                        output: n.output,
                        error: n.error,
                    },
                }));

                const loadedEdges = (plan.edges || []).map((e: any) => ({
                    id: e.id || `e-${e.source}-${e.target}`,
                    source: e.source,
                    target: e.target,
                    animated: true,
                    style: { stroke: 'var(--status-pending)', strokeWidth: 2 },
                }));

                setNodes(loadedNodes);
                setEdges(loadedEdges);
                setActivePlanId(activePlanIdFromChat);
                setIsEditMode(true);
                hasFitView.current = false;
                addToast('Plan cargado desde IA — edita y ejecuta.', 'success');
            } catch {
                addToast('No se pudo cargar el plan generado.', 'error');
            }
        };

        loadPlan();
    }, [activePlanIdFromChat, setNodes, setEdges, addToast]);

    useEffect(() => {
        if (!isEditMode || !activePlanId) return;

        const eventSource = new EventSource(`${API_BASE}/ops/stream`, { withCredentials: true });
        eventSource.onmessage = (event) => {
            try {
                const parsed = JSON.parse(event.data);
                const eventType = parsed?.event;
                const data = parsed?.data;

                if (eventType === 'custom_node_status' && data?.plan_id === activePlanId) {
                    setNodes((nds) => nds.map((n: any) => {
                        if (n.id !== data.node_id) return n;
                        return {
                            ...n,
                            data: {
                                ...n.data,
                                status: data.status || n.data?.status,
                                output: data.output ?? n.data?.output,
                                error: data.error ?? n.data?.error,
                            },
                        };
                    }));
                }

                if (eventType === 'custom_plan_finished' && data?.plan_id === activePlanId) {
                    setIsExecuting(false);
                    addToast(
                        data.status === 'done' ? 'Plan completado.' : 'Plan finalizado con errores.',
                        data.status === 'done' ? 'success' : 'error',
                    );
                }
            } catch {
                // ignore malformed events
            }
        };

        return () => eventSource.close();
    }, [isEditMode, activePlanId, setNodes, addToast]);

    const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
        onNodeSelect(node.id);
        if (isEditMode) {
            setSelectedEditNodeId(node.id);
        }
    }, [onNodeSelect, isEditMode]);

    const createManualNodeAtClientPoint = useCallback((event: React.MouseEvent) => {
        const target = event.target as HTMLElement;
        if (!target.closest('.react-flow__pane')) return;

        const reactFlowBounds = target.closest('.react-flow')?.getBoundingClientRect();
        if (!reactFlowBounds) return;

        const position = project({
            x: event.clientX - reactFlowBounds.left,
            y: event.clientY - reactFlowBounds.top,
        });

        const newNode = {
            id: `manual_${Date.now()}`,
            type: 'custom',
            position,
            data: {
                label: `Node ${nodes.length + 1}`,
                status: 'pending',
                trustLevel: 'supervised',
                node_type: 'worker',
                role: 'worker',
                role_definition: '',
                model: 'auto',
                provider: 'auto',
                prompt: '',
                is_orchestrator: false,
            },
        };

        setNodes((nds) => nds.concat(newNode));
        setSelectedEditNodeId(newNode.id);
        addToast('Nodo manual creado', 'info');
    }, [project, setNodes, addToast, nodes.length]);

    const createManualNode = useCallback(() => {
        const newNode = {
            id: `manual_${Date.now()}`,
            type: 'custom',
            position: { x: 120 + nodes.length * 30, y: 120 + nodes.length * 20 },
            data: {
                label: `Node ${nodes.length + 1}`,
                status: 'pending',
                trustLevel: 'supervised',
                node_type: 'worker',
                role: 'worker',
                role_definition: '',
                model: 'auto',
                provider: 'auto',
                prompt: '',
                is_orchestrator: false,
            },
        };
        setNodes((nds) => nds.concat(newNode));
        setSelectedEditNodeId(newNode.id);
        addToast('Nodo manual creado', 'info');
    }, [setNodes, addToast, nodes.length]);

    const onPaneClick = useCallback((event: React.MouseEvent) => {
        if (isEditMode) {
            if (event.detail >= 2) {
                createManualNodeAtClientPoint(event);
                return;
            }
            setSelectedEditNodeId(null);
            return;
        }

        onNodeSelect(null);
    }, [isEditMode, onNodeSelect, createManualNodeAtClientPoint]);

    const onConnect = useCallback((params: Connection) => {
        if (params.source && params.target) {
            setEdges((eds) => addEdge({ ...params, animated: true, style: { stroke: 'var(--status-pending)', strokeWidth: 2 } }, eds));
        }
    }, [setEdges]);

    const onEdgeClick: EdgeMouseHandler = useCallback((event, edge) => {
        event.preventDefault();
        setEdges((eds) => eds.filter((e: any) => e.id !== edge.id));
        addToast('Conexión eliminada.', 'info');
    }, [setEdges, addToast]);

    const selectedEditNode = useMemo(
        () => nodes.find((n: any) => n.id === selectedEditNodeId) as any,
        [nodes, selectedEditNodeId],
    );

    const updateSelectedNodeData = useCallback((field: string, value: any) => {
        if (!selectedEditNodeId) return;
        setNodes((nds) => nds.map((n: any) => {
            if (n.id !== selectedEditNodeId) return n;
            const nextData = { ...n.data, [field]: value };
            if (field === 'node_type') {
                nextData.role = value;
                nextData.is_orchestrator = value === 'orchestrator';
            }
            return { ...n, data: nextData };
        }));
    }, [selectedEditNodeId, setNodes]);

    const handleSaveDraft = useCallback(async () => {
        setIsSaving(true);
        if (nodes.length === 0) {
            addToast('No hay nodos para guardar en borrador manual', 'error');
            setIsSaving(false);
            return;
        }

        const rootCount = nodes.filter((n: any) => n?.data?.is_orchestrator || n?.data?.node_type === 'orchestrator').length;
        if (rootCount !== 1) {
            addToast('Debes definir exactamente 1 nodo orquestador madre.', 'error');
            setIsSaving(false);
            return;
        }

        const nodeIds = new Set(nodes.map((n: any) => n.id));
        for (const e of edges as any[]) {
            if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) {
                addToast('Hay conexiones inválidas entre nodos.', 'error');
                setIsSaving(false);
                return;
            }
        }

        const adj = new Map<string, string[]>();
        nodes.forEach((n: any) => adj.set(n.id, []));
        edges.forEach((e: any) => adj.get(e.source)?.push(e.target));
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
        for (const n of nodes as any[]) {
            if (!visited.has(n.id) && hasCycle(n.id)) {
                addToast('El grafo contiene ciclos. Rompe el ciclo para guardar.', 'error');
                setIsSaving(false);
                return;
            }
        }

        try {
            const planPayload = {
                name: `${planName}`,
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
                    is_orchestrator: Boolean(n.data?.is_orchestrator || n.data?.node_type === 'orchestrator'),
                    status: n.data?.status || 'pending',
                    position: n.position,
                    depends_on: edges.filter((e: any) => e.target === n.id).map((e: any) => e.source),
                    config: {},
                })),
                edges: edges.map((e: any) => ({
                    id: e.id || `e-${e.source}-${e.target}`,
                    source: e.source,
                    target: e.target,
                })),
            };

            // PUT to update existing plan, POST to create new
            const url = activePlanId
                ? `${API_BASE}/ops/custom-plans/${activePlanId}`
                : `${API_BASE}/ops/custom-plans`;
            const method = activePlanId ? 'PUT' : 'POST';

            const response = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(planPayload),
                credentials: 'include',
            });

            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const payload = await response.json();
                    detail = payload?.detail || detail;
                } catch {
                    // ignore
                }
                throw new Error(detail);
            }

            const savedPlan = await response.json();
            setActivePlanId(savedPlan.id);
            addToast(activePlanId ? 'Plan actualizado' : 'Plan guardado', 'success');
        } catch (error: any) {
            addToast(`No se pudo guardar el plan manual: ${error?.message || 'error desconocido'}`, 'error');
        } finally {
            setIsSaving(false);
        }
    }, [nodes, edges, addToast, fetchGraphData, planName, planDescription]);

    const handleExecuteSavedPlan = useCallback(async () => {
        if (!activePlanId) {
            addToast('Guarda primero el plan manual antes de ejecutarlo.', 'info');
            return;
        }
        setIsExecuting(true);
        try {
            const res = await fetch(`${API_BASE}/ops/custom-plans/${activePlanId}/execute`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!res.ok) {
                let detail = `HTTP ${res.status}`;
                try {
                    const payload = await res.json();
                    detail = payload?.detail || detail;
                } catch {
                    // ignore
                }
                throw new Error(detail);
            }
            addToast('Ejecución del plan iniciada.', 'success');
        } catch (error: any) {
            addToast(`No se pudo iniciar la ejecución del plan: ${error?.message || 'error desconocido'}.`, 'error');
        } finally {
            setIsExecuting(false);
        }
    }, [activePlanId, addToast]);

    const deleteSelectedNode = useCallback(() => {
        if (!selectedEditNodeId) return;
        setNodes((nds) => nds.filter((n: any) => n.id !== selectedEditNodeId));
        setEdges((eds) => eds.filter((e: any) => e.source !== selectedEditNodeId && e.target !== selectedEditNodeId));
        setSelectedEditNodeId(null);
        addToast('Nodo eliminado.', 'info');
    }, [selectedEditNodeId, setNodes, setEdges, addToast]);

    return (
        <div className="w-full h-full bg-surface-1">
            <ReactFlow
                nodes={nodes.map(n => ({ ...n, selected: n.id === selectedNodeId }))}
                edges={edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                onNodeClick={onNodeClick}
                onPaneClick={onPaneClick}
                onConnect={onConnect}
                onEdgeClick={onEdgeClick}
                fitView={!hasFitView.current}
                onInit={() => { hasFitView.current = true; }}
                proOptions={{ hideAttribution: true }}
                minZoom={0.3}
                maxZoom={2}
                defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
            >
                <Background color="var(--border-subtle)" gap={24} size={1} />
                <Controls showInteractive={false} />
                <MiniMap
                    nodeColor={(node) => {
                        const nType = (node as any).data?.node_type;
                        if (nType === 'orchestrator') return '#22d3ee';
                        if (nType === 'worker') return '#60a5fa';
                        if (nType === 'reviewer') return '#fb923c';
                        if (nType === 'researcher') return '#c084fc';
                        if (nType === 'tool') return '#34d399';
                        if (nType === 'human_gate') return '#f59e0b';
                        return 'var(--status-pending)';
                    }}
                    maskColor="rgba(0, 0, 0, 0.7)"
                    className="!bg-[var(--surface-2)] !border-[var(--border-primary)] !rounded-xl"
                    style={{ width: 140, height: 90 }}
                />
                {draftInfo ? (
                    <PlanOverlayCard
                        prompt={draftInfo.prompt}
                        draftId={draftInfo.draftId}
                        onApprove={() => onApprovePlan?.(draftInfo.draftId)}
                        onReject={() => onRejectPlan?.(draftInfo.draftId)}
                        onEdit={() => onEditPlan?.()}
                        loading={planLoading}
                    />
                ) : (
                    <Panel
                        position="top-left"
                        className="bg-surface-2/90 backdrop-blur-xl px-3 py-1.5 rounded-lg border border-border-primary text-[10px] text-text-secondary font-mono uppercase tracking-wider"
                    >
                        Live Orchestration Graph
                    </Panel>
                )}

                {isEditMode && (
                    <Panel position="top-left" className="bg-surface-2/95 border border-border-primary rounded-xl p-3 min-w-[340px]">
                        <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-2">Plan Composer (unificado)</div>
                        <input
                            value={planName}
                            onChange={(e) => setPlanName(e.target.value)}
                            className="w-full mb-1 bg-surface-3 border border-border-primary rounded-lg px-2 py-1 text-xs text-text-primary"
                            placeholder="Nombre del plan"
                        />
                        <input
                            value={planDescription}
                            onChange={(e) => setPlanDescription(e.target.value)}
                            className="w-full bg-surface-3 border border-border-primary rounded-lg px-2 py-1 text-[11px] text-text-secondary"
                            placeholder="Descripción"
                        />
                    </Panel>
                )}

                {isEditMode && (
                    <Panel position="top-right" className="mr-3 mt-3">
                        <button
                            onClick={createManualNode}
                            className="w-10 h-10 rounded-full bg-accent-primary text-white flex items-center justify-center shadow-lg shadow-accent-primary/30 hover:scale-110 active:scale-95 transition-all"
                            title="Añadir nodo"
                        >
                            <Plus size={20} />
                        </button>
                    </Panel>
                )}

                {progressStats && (
                    <Panel position="top-center" className="bg-surface-2/90 backdrop-blur-xl px-4 py-2 rounded-xl border border-border-primary min-w-[200px] shadow-lg">
                        <div className="flex justify-between items-center mb-1.5">
                            <span className="text-[10px] text-text-primary font-semibold uppercase tracking-wider flex items-center gap-1.5">
                                <div className="w-1.5 h-1.5 rounded-full bg-status-running animate-status-pulse" />
                                Ejecución en progreso
                            </span>
                            <span className="text-[10px] text-text-secondary font-mono">
                                {progressStats.done} / {progressStats.total}
                            </span>
                        </div>
                        <div className="h-1 w-full bg-surface-3 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-accent-primary transition-all duration-500 ease-out"
                                style={{ width: `${progressStats.percent}%` }}
                            />
                        </div>
                    </Panel>
                )}

                {/* Edit Mode Toolbar */}
                <Panel position="bottom-center" className="mb-4">
                    <div className="flex items-center bg-surface-2/90 backdrop-blur-xl rounded-full border border-border-primary p-1.5 shadow-xl">
                        {!isEditMode ? (
                            <button
                                onClick={() => setIsEditMode(true)}
                                className="flex items-center gap-2 px-4 py-2 hover:bg-surface-3 text-text-secondary hover:text-text-primary rounded-full transition-colors text-[11px] font-medium"
                            >
                                <Edit2 size={14} />
                                Modo Edición
                            </button>
                        ) : (
                            <>
                                <button
                                    onClick={createManualNode}
                                    className="flex items-center gap-2 px-3 py-2 hover:bg-surface-3 text-text-secondary hover:text-text-primary rounded-full transition-colors text-[11px] font-medium"
                                >
                                    <Plus size={14} />
                                    Añadir Nodo
                                </button>
                                <div className="px-3 py-1 text-[10px] text-text-secondary flex items-center">
                                    Doble click en canvas = crear nodo · arrastra handles = crear edge
                                </div>
                                <button
                                    onClick={handleSaveDraft}
                                    disabled={isSaving}
                                    className="flex items-center gap-2 px-4 py-2 bg-accent-trust/10 text-accent-trust hover:bg-accent-trust/20 rounded-full transition-colors text-[11px] font-bold tracking-wide mr-1"
                                >
                                    <Save size={14} />
                                    {isSaving ? 'Guardando…' : 'Guardar Plan'}
                                </button>
                                <button
                                    onClick={handleExecuteSavedPlan}
                                    disabled={isExecuting || !activePlanId}
                                    className="flex items-center gap-2 px-4 py-2 bg-accent-primary/10 text-accent-primary hover:bg-accent-primary/20 disabled:opacity-50 rounded-full transition-colors text-[11px] font-bold tracking-wide mr-1"
                                >
                                    <Play size={14} />
                                    Ejecutar
                                </button>
                                <button
                                    onClick={() => {
                                        setIsEditMode(false);
                                        fetchGraphData(); // reload normal graph
                                    }}
                                    className="flex items-center justify-center w-8 h-8 hover:bg-accent-alert/10 text-text-secondary hover:text-accent-alert rounded-full transition-colors"
                                    title="Cancelar edición"
                                >
                                    <X size={14} />
                                </button>
                            </>
                        )}
                    </div>
                </Panel>

                {isEditMode && selectedEditNode && (
                    <Panel position="top-right" className="w-[340px] max-h-[80vh] overflow-y-auto bg-surface-2/95 backdrop-blur-xl border border-border-primary rounded-xl p-4 shadow-xl">
                        <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-3">Configuración de Nodo</h3>
                        <div className="space-y-3">
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Nombre</label>
                                <input
                                    value={selectedEditNode.data?.label || ''}
                                    onChange={(e) => updateSelectedNodeData('label', e.target.value)}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs"
                                />
                            </div>
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Tipo de Nodo</label>
                                <select
                                    value={selectedEditNode.data?.node_type || 'worker'}
                                    onChange={(e) => updateSelectedNodeData('node_type', e.target.value)}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs"
                                >
                                    {NODE_TYPES.map((type) => (
                                        <option key={type} value={type}>{type}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Modelo</label>
                                <select
                                    value={selectedEditNode.data?.model || 'auto'}
                                    onChange={(e) => updateSelectedNodeData('model', e.target.value)}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs"
                                >
                                    <option value="auto">auto (usa el provider activo)</option>
                                    {models.map((m) => (
                                        <option key={m.id} value={m.id}>{m.label || m.id}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Provider</label>
                                <select
                                    value={selectedEditNode.data?.provider || 'auto'}
                                    onChange={(e) => updateSelectedNodeData('provider', e.target.value)}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs"
                                >
                                    <option value="auto">auto (provider activo)</option>
                                    <option value="openai">OpenAI</option>
                                    <option value="ollama">Ollama (local)</option>
                                    <option value="groq">Groq</option>
                                    <option value="openrouter">OpenRouter</option>
                                    <option value="codex">Codex CLI</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Definición de Rol</label>
                                <select
                                    value=""
                                    onChange={(e) => {
                                        const tpl = ROLE_DEFINITION_TEMPLATES[e.target.value];
                                        if (tpl) updateSelectedNodeData('role_definition', tpl);
                                    }}
                                    className="w-full mt-1 mb-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs"
                                >
                                    <option value="">Aplicar plantilla de rol…</option>
                                    {NODE_TYPES.map((type) => (
                                        <option key={type} value={type}>{type}</option>
                                    ))}
                                </select>
                                <textarea
                                    value={selectedEditNode.data?.role_definition || ''}
                                    onChange={(e) => updateSelectedNodeData('role_definition', e.target.value)}
                                    rows={3}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs resize-none"
                                />
                            </div>
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Prompt / Instructions</label>
                                <textarea
                                    value={selectedEditNode.data?.prompt || ''}
                                    onChange={(e) => updateSelectedNodeData('prompt', e.target.value)}
                                    rows={6}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs resize-none"
                                />
                                <div className="flex items-start gap-2 text-[10px] text-text-secondary bg-blue-500/5 p-2 rounded border border-blue-500/10 mt-1">
                                    <Info size={12} className="shrink-0 mt-0.5" />
                                    <span>Las salidas de nodos dependientes se inyectarán automáticamente en el contexto de este nodo.</span>
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div>
                                    <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Status</label>
                                    <div className="mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs text-text-secondary">
                                        {selectedEditNode.data?.status || 'pending'}
                                    </div>
                                </div>
                                <div>
                                    <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Node ID</label>
                                    <div className="mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-[11px] text-text-secondary font-mono truncate">
                                        {selectedEditNode.id}
                                    </div>
                                </div>
                            </div>
                            {selectedEditNode.data?.error && (
                                <div>
                                    <label className="text-[10px] uppercase tracking-wider text-red-300">Error</label>
                                    <div className="mt-1 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-200 whitespace-pre-wrap">
                                        {selectedEditNode.data.error}
                                    </div>
                                </div>
                            )}
                            {selectedEditNode.data?.output && (
                                <div>
                                    <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Output</label>
                                    <div className="mt-1 max-h-36 overflow-y-auto bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs text-text-secondary whitespace-pre-wrap">
                                        {selectedEditNode.data.output}
                                    </div>
                                </div>
                            )}
                            <div>
                                <label className="text-[10px] uppercase tracking-wider text-text-tertiary">Descripción del plan</label>
                                <textarea
                                    value={planDescription}
                                    onChange={(e) => setPlanDescription(e.target.value)}
                                    rows={2}
                                    className="w-full mt-1 bg-surface-3 border border-border-primary rounded-lg px-3 py-2 text-xs resize-none"
                                />
                            </div>
                            <button
                                onClick={deleteSelectedNode}
                                className="w-full flex items-center justify-center gap-2 mt-2 px-3 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20 text-xs font-semibold"
                            >
                                <Trash2 size={14} />
                                Eliminar nodo seleccionado
                            </button>
                        </div>
                    </Panel>
                )}
            </ReactFlow>
        </div>
    );
};
