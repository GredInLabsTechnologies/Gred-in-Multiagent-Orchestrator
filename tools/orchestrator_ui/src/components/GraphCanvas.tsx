import React, { useEffect, useCallback, useMemo, useRef } from 'react';
import ReactFlow, {
    Background,
    Controls,
    MiniMap,
    Panel,
    useNodesState,
    useEdgesState,
    NodeMouseHandler,
    useReactFlow,
    Connection,
    addEdge,
    EdgeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { AnimatePresence } from 'framer-motion';
import { Plus } from 'lucide-react';
import { ComposerNode } from './ComposerNode';
import { PlanOverlayCard } from './PlanOverlayCard';
import { GraphToolbar } from './Graph/GraphToolbar';
import { NodeEditor } from './Graph/NodeEditor';
import { ProgressBar } from './Graph/ProgressBar';
import { AnimatedEdge } from './Graph/AnimatedEdge';
import {
    useGraphStore,
    normalizeServerNodes,
    normalizeServerEdges,
    toEditableNode,
    extractDraftInfo,
    computeProgress,
    validateGraph,
    buildPlanPayload,
    ROLE_TEMPLATES,
} from './Graph/useGraphStore';
import { API_BASE } from '../types';
import { useToast } from './Toast';
import { useAvailableModels } from '../hooks/useAvailableModels';

/* ── Node & Edge types ─────────────────────────────── */

const nodeTypes = { custom: ComposerNode };
const edgeTypes = { animated: AnimatedEdge };

/* ── Props ─────────────────────────────────────────── */

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

/* ── Component ─────────────────────────────────────── */

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
    const { project } = useReactFlow();
    const hasFitViewRef = useRef(false);
    const keysPressed = useRef(new Set<string>());
    const tabConnectSourceRef = useRef<string | null>(null);

    /* Store slices — use selectors to avoid full-store re-renders */
    const isEditMode = useGraphStore((s) => s.isEditMode);
    const selectedEditNodeId = useGraphStore((s) => s.selectedEditNodeId);
    const planName = useGraphStore((s) => s.planName);
    const planDescription = useGraphStore((s) => s.planDescription);
    const activePlanId = useGraphStore((s) => s.activePlanId);

    /* ── Track user-moved positions ── */
    const onNodesChangeRef = useRef(onNodesChange);
    onNodesChangeRef.current = onNodesChange;
    const handleNodesChange = useCallback(
        (changes: any[]) => {
            onNodesChangeRef.current(changes);
            for (const change of changes) {
                if (change.type === 'position' && change.position) {
                    useGraphStore.getState().trackPosition(change.id, { ...change.position });
                }
            }
        },
        [],
    );

    /* ── Derived data ── */
    const draftInfo = useMemo(() => extractDraftInfo(nodes), [nodes]);
    const hasRunningNodes = useMemo(() => nodes.some((n) => n.data?.status === 'running'), [nodes]);
    const progressStats = useMemo(() => computeProgress(nodes, hasRunningNodes), [nodes, hasRunningNodes]);
    const selectedEditNode = useMemo(
        () => nodes.find((n: any) => n.id === selectedEditNodeId) as any,
        [nodes, selectedEditNodeId],
    );

    /* ── Stable refs for fetch callback ── */
    const onNodeCountChangeRef = useRef(onNodeCountChange);
    onNodeCountChangeRef.current = onNodeCountChange;
    const addToastRef = useRef(addToast);
    addToastRef.current = addToast;
    const setNodesRef = useRef(setNodes);
    setNodesRef.current = setNodes;
    const setEdgesRef = useRef(setEdges);
    setEdgesRef.current = setEdges;

    /* ── Fetch graph data ── */
    const fetchGraphData = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/ui/graph`, { credentials: 'include' });
            if (response.status === 401 || response.status === 403) {
                onNodeCountChangeRef.current?.(-1);
                return;
            }
            if (!response.ok) {
                addToastRef.current(`Error al cargar el grafo (HTTP ${response.status})`, 'error');
                onNodeCountChangeRef.current?.(0);
                return;
            }

            const data = await response.json();
            const graphStore = useGraphStore.getState();
            const formattedEdges = normalizeServerEdges(data.edges);
            const nodesWithLiveState = normalizeServerNodes(data.nodes, graphStore.userPositions);

            onNodeCountChangeRef.current?.(nodesWithLiveState.length);

            // Detect new graph
            const newNodeIds = nodesWithLiveState.map((n: any) => n.id).sort().join(',');
            if (newNodeIds !== graphStore.prevNodeIds) {
                graphStore.resetPositions();
                hasFitViewRef.current = false;
                graphStore.setPrevNodeIds(newNodeIds);
            }

            setNodesRef.current(nodesWithLiveState);
            setEdgesRef.current(formattedEdges);
        } catch {
            addToastRef.current('Error al cargar datos del grafo', 'error');
            onNodeCountChangeRef.current?.(0);
        }
    }, []);

    /* ── Polling ── */
    useEffect(() => {
        if (isEditMode) return;
        fetchGraphData();
        const intervalTime = hasRunningNodes ? 2000 : 5000;
        const interval = setInterval(fetchGraphData, intervalTime);
        return () => clearInterval(interval);
    }, [fetchGraphData, hasRunningNodes, isEditMode]);

    /* ── Edit mode init ── */
    useEffect(() => {
        if (!isEditMode) {
            useGraphStore.getState().setSelectedEditNodeId(null);
            return;
        }
        if (nodes.length === 0) {
            const seedNode = {
                id: `node_${Date.now()}`,
                type: 'custom',
                position: { x: 220, y: 120 },
                data: {
                    label: 'Tarea Inicial',
                    status: 'pending',
                    trustLevel: 'supervised',
                    node_type: 'orchestrator',
                    role: 'orchestrator',
                    role_definition: ROLE_TEMPLATES.orchestrator,
                    model: 'auto',
                    provider: 'auto',
                    prompt: 'Define el plan y delega tareas a los workers.',
                    is_orchestrator: true,
                },
            };
            setNodes([seedNode] as any);
            useGraphStore.getState().setSelectedEditNodeId(seedNode.id);
            return;
        }
        setNodes((nds) => nds.map((n: any) => toEditableNode(n)));
    }, [isEditMode, setNodes]);

    /* ── Load plan from chat ── */
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
                    type: 'animated',
                    animated: true,
                    style: { stroke: 'var(--status-pending)', strokeWidth: 2 },
                }));

                setNodes(loadedNodes);
                setEdges(loadedEdges);
                useGraphStore.getState().setActivePlanId(activePlanIdFromChat);
                useGraphStore.getState().setEditMode(true);
                hasFitViewRef.current = false;
                addToast('Plan cargado desde IA — edita y ejecuta.', 'success');
            } catch {
                addToast('No se pudo cargar el plan generado.', 'error');
            }
        };
        loadPlan();
    }, [activePlanIdFromChat, setNodes, setEdges, addToast]);

    /* -- Sync external selection -- */
    useEffect(() => {
        if (selectedNodeId) {
            setNodes((nds) => nds.map(n =>
                n.id === selectedNodeId && !n.selected ? { ...n, selected: true } : n
            ));
        }
    }, [selectedNodeId, setNodes]);

    /* ── SSE for execution updates ── */
    useEffect(() => {
        if (!isEditMode || !activePlanId) return;
        const eventSource = new EventSource(`${API_BASE}/ops/stream`, { withCredentials: true });
        eventSource.onmessage = (event) => {
            try {
                const parsed = JSON.parse(event.data);
                const eventType = parsed?.event;
                const data = parsed?.data;
                if (eventType === 'custom_node_status' && data?.plan_id === activePlanId) {
                    setNodes((nds) =>
                        nds.map((n: any) => {
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
                        }),
                    );
                }
                if (eventType === 'custom_plan_finished' && data?.plan_id === activePlanId) {
                    useGraphStore.getState().setIsExecuting(false);
                    addToast(
                        data.status === 'done' ? 'Plan completado.' : 'Plan finalizado con errores.',
                        data.status === 'done' ? 'success' : 'error',
                    );
                }
            } catch {
                /* ignore malformed events */
            }
        };
        return () => eventSource.close();
    }, [isEditMode, activePlanId, setNodes, addToast]);

    /* ── Interactions ── */
    const onNodeClick: NodeMouseHandler = useCallback(
        (_event, node) => {
            if (isEditMode && keysPressed.current.has('tab')) {
                if (!tabConnectSourceRef.current) {
                    tabConnectSourceRef.current = node.id;
                    addToast('Nodo origen seleccionado para conectar. Haz tab+click en el destino.', 'info');
                } else {
                    if (tabConnectSourceRef.current !== node.id) {
                        const source = tabConnectSourceRef.current;
                        const target = node.id;
                        setEdges((eds) => addEdge({
                            id: `e-${source}-${target}-${Date.now()}`,
                            source, target, type: 'animated', animated: true, style: { stroke: 'var(--status-pending)', strokeWidth: 2 }
                        }, eds));
                        addToast('Nodos conectados.', 'success');
                    }
                    tabConnectSourceRef.current = null;
                }
                return;
            } else {
                tabConnectSourceRef.current = null;
            }

            onNodeSelect(node.id);
            if (isEditMode) useGraphStore.getState().setSelectedEditNodeId(node.id);
        },
        [onNodeSelect, isEditMode, setEdges, addToast],
    );

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
        useGraphStore.getState().setSelectedEditNodeId(newNode.id);
        addToast('Nodo manual creado', 'info');
    }, [setNodes, addToast, nodes.length]);

    const createManualNodeAtClientPoint = useCallback(
        (event: React.MouseEvent) => {
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
            useGraphStore.getState().setSelectedEditNodeId(newNode.id);
            addToast('Nodo manual creado', 'info');
        },
        [project, setNodes, addToast, nodes.length],
    );

    const onPaneClick = useCallback(
        (event: React.MouseEvent) => {
            if (isEditMode) {
                if (event.detail >= 2) {
                    createManualNodeAtClientPoint(event);
                    return;
                }
                useGraphStore.getState().setSelectedEditNodeId(null);
                return;
            }
            onNodeSelect(null);
        },
        [isEditMode, onNodeSelect, createManualNodeAtClientPoint],
    );

    const onConnect = useCallback(
        (params: Connection) => {
            if (params.source && params.target) {
                setEdges((eds) =>
                    addEdge(
                        { ...params, type: 'animated', animated: true, style: { stroke: 'var(--status-pending)', strokeWidth: 2 } },
                        eds,
                    ),
                );
            }
        },
        [setEdges],
    );

    const onEdgeClick: EdgeMouseHandler = useCallback(
        (_event, edge) => {
            if (!isEditMode) return;
            setEdges((eds) => eds.filter((e: any) => e.id !== edge.id));
            addToast('Conexion eliminada.', 'info');
        },
        [setEdges, addToast, isEditMode],
    );

    /* ── Node editing ── */
    const updateSelectedNodeData = useCallback(
        (field: string, value: any) => {
            if (!selectedEditNodeId) return;
            setNodes((nds) =>
                nds.map((n: any) => {
                    if (n.id !== selectedEditNodeId) return n;
                    const nextData = { ...n.data, [field]: value };
                    if (field === 'node_type') {
                        nextData.role = value;
                        nextData.is_orchestrator = value === 'orchestrator';
                    }
                    return { ...n, data: nextData };
                }),
            );
        },
        [selectedEditNodeId, setNodes],
    );

    const deleteSelectedElements = useCallback(() => {
        if (!isEditMode) return;
        const selectedNodes = nodes.filter((n: any) => n.selected || n.id === selectedEditNodeId);
        if (selectedNodes.length === 0) return;

        const ids = selectedNodes.map((n: any) => n.id);
        setNodes((nds) => nds.filter((n: any) => !ids.includes(n.id)));
        setEdges((eds) => eds.filter((e: any) => !ids.includes(e.source) && !ids.includes(e.target)));

        if (selectedEditNodeId && ids.includes(selectedEditNodeId)) {
            useGraphStore.getState().setSelectedEditNodeId(null);
        }
        addToast(`${ids.length} nodo(s) eliminado(s)`, 'info');
    }, [isEditMode, nodes, selectedEditNodeId, setNodes, setEdges, addToast]);

    const duplicateSelectedElements = useCallback(() => {
        if (!isEditMode) return;
        const selected = nodes.filter((n: any) => n.selected || n.id === selectedEditNodeId);
        if (selected.length === 0) return;

        const newNodes: any[] = [];
        const newEdges: any[] = [];
        const idMap = new Map<string, string>();

        // Offset for duplicates
        const offset = 50 + Math.random() * 20;

        selected.forEach((n: any) => {
            const newId = `${n.id}_copy_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
            idMap.set(n.id, newId);
            newNodes.push({
                id: newId,
                type: n.type,
                position: { x: n.position.x + offset, y: n.position.y + offset },
                data: { ...n.data },
                selected: true, // Only select the new duplicates
            });
        });

        // Find edges between selected nodes
        const selectedIds = new Set(selected.map((n: any) => n.id));
        edges.forEach((e: any) => {
            if (selectedIds.has(e.source) && selectedIds.has(e.target)) {
                const newSource = idMap.get(e.source)!;
                const newTarget = idMap.get(e.target)!;
                newEdges.push({
                    id: `e-${newSource}-${newTarget}-${Date.now()}`,
                    source: newSource,
                    target: newTarget,
                    type: e.type,
                    animated: e.animated,
                    style: e.style,
                    selected: true,
                });
            }
        });

        // Deselect original nodes
        setNodes((nds) => [
            ...nds.map((n: any) => ({ ...n, selected: false })),
            ...newNodes
        ]);
        setEdges((eds) => [
            ...eds.map((e: any) => ({ ...e, selected: false })),
            ...newEdges
        ]);

        // Select the newest duplicate node for the editor panel if it was a single node
        if (selected.length === 1) {
            useGraphStore.getState().setSelectedEditNodeId(newNodes[0].id);
        } else {
            useGraphStore.getState().setSelectedEditNodeId(null);
        }
        addToast(`${newNodes.length} nodo(s) duplicado(s)`, 'success');
    }, [isEditMode, nodes, edges, selectedEditNodeId, setNodes, setEdges, addToast]);

    const deleteSelectedNode = useCallback(() => {
        deleteSelectedElements();
    }, [deleteSelectedElements]);

    useEffect(() => {
        const handleGlobalKeyDown = (e: KeyboardEvent) => {
            keysPressed.current.add(e.key.toLowerCase());

            // Alt+X -> delete selected
            if (e.altKey && e.key.toLowerCase() === 'x') {
                e.preventDefault();
                deleteSelectedElements();
            }

            // Alt+D -> duplicate selected
            if (e.altKey && e.key.toLowerCase() === 'd') {
                e.preventDefault();
                duplicateSelectedElements();
            }
        };
        const handleGlobalKeyUp = (e: KeyboardEvent) => {
            keysPressed.current.delete(e.key.toLowerCase());
        };

        window.addEventListener('keydown', handleGlobalKeyDown);
        window.addEventListener('keyup', handleGlobalKeyUp);
        return () => {
            window.removeEventListener('keydown', handleGlobalKeyDown);
            window.removeEventListener('keyup', handleGlobalKeyUp);
        };
    }, [deleteSelectedElements, duplicateSelectedElements]);

    /* ── Save & Execute ── */
    const handleSaveDraft = useCallback(async () => {
        useGraphStore.getState().setIsSaving(true);
        const error = validateGraph(nodes, edges);
        if (error) {
            addToast(error, 'error');
            useGraphStore.getState().setIsSaving(false);
            return;
        }
        try {
            const payload = buildPlanPayload(nodes, edges, planName, planDescription);
            const url = activePlanId
                ? `${API_BASE}/ops/custom-plans/${activePlanId}`
                : `${API_BASE}/ops/custom-plans`;
            const method = activePlanId ? 'PUT' : 'POST';
            const response = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                credentials: 'include',
            });
            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const p = await response.json();
                    detail = p?.detail || detail;
                } catch { /* ignore */ }
                throw new Error(detail);
            }
            const savedPlan = await response.json();
            useGraphStore.getState().setActivePlanId(savedPlan.id);
            addToast(activePlanId ? 'Plan actualizado' : 'Plan guardado', 'success');
        } catch (err: any) {
            addToast(`No se pudo guardar el plan: ${err?.message || 'error desconocido'}`, 'error');
        } finally {
            useGraphStore.getState().setIsSaving(false);
        }
    }, [nodes, edges, addToast, planName, planDescription, activePlanId]);

    const handleExecute = useCallback(async () => {
        if (!activePlanId) {
            addToast('Guarda primero el plan antes de ejecutarlo.', 'info');
            return;
        }
        useGraphStore.getState().setIsExecuting(true);
        try {
            const res = await fetch(`${API_BASE}/ops/custom-plans/${activePlanId}/execute`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!res.ok) {
                let detail = `HTTP ${res.status}`;
                try {
                    const p = await res.json();
                    detail = p?.detail || detail;
                } catch { /* ignore */ }
                throw new Error(detail);
            }
            addToast('Ejecucion del plan iniciada.', 'success');
        } catch (err: any) {
            addToast(`No se pudo iniciar la ejecucion: ${err?.message || 'error desconocido'}`, 'error');
        } finally {
            useGraphStore.getState().setIsExecuting(false);
        }
    }, [activePlanId, addToast]);

    /* ── MiniMap node colors ── */
    const miniMapNodeColor = useCallback((node: any) => {
        const nType = node.data?.node_type;
        if (nType === 'orchestrator') return '#22d3ee';
        if (nType === 'worker') return '#60a5fa';
        if (nType === 'reviewer') return '#fb923c';
        if (nType === 'researcher') return '#c084fc';
        if (nType === 'tool') return '#34d399';
        if (nType === 'human_gate') return '#f59e0b';
        return 'var(--status-pending)';
    }, []);

    /* ── Render ─────────────────────────────────────── */

    const onSelectionChange = useCallback(({ nodes: selectedNodes }: any) => {
        if (selectedNodes.length === 1) {
            onNodeSelect(selectedNodes[0].id);
            if (isEditMode) useGraphStore.getState().setSelectedEditNodeId(selectedNodes[0].id);
        } else if (selectedNodes.length === 0) {
            // Unselect on empty selection
            onNodeSelect(null);
            if (isEditMode) useGraphStore.getState().setSelectedEditNodeId(null);
        }
    }, [isEditMode, onNodeSelect]);

    return (
        <div className="w-full h-full bg-surface-1">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={onEdgesChange}
                onSelectionChange={onSelectionChange}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                onNodeClick={onNodeClick}
                onPaneClick={onPaneClick}
                onConnect={onConnect}
                onEdgeClick={onEdgeClick}
                fitView={!hasFitViewRef.current}
                onInit={() => { hasFitViewRef.current = true; }}
                proOptions={{ hideAttribution: true }}
                selectionOnDrag={true}
                panOnScroll={true}
                panOnDrag={[1, 2]}
                minZoom={0.3}
                maxZoom={2}
                defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
            >
                <Background color="var(--border-subtle)" gap={24} size={1} />
                <Controls showInteractive={false} />
                <MiniMap
                    nodeColor={miniMapNodeColor}
                    maskColor="rgba(0, 0, 0, 0.7)"
                    className="!bg-[var(--surface-2)] !border-[var(--border-primary)] !rounded-xl"
                    style={{ width: 140, height: 90 }}
                />

                {/* Draft overlay OR label */}
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
                        className="bg-surface-1/80 backdrop-blur-xl px-3 py-1.5 rounded-xl border border-white/[0.06] text-[10px] text-text-secondary font-mono uppercase tracking-wider"
                    >
                        Grafo de Orquestación
                    </Panel>
                )}

                {/* Edit mode: plan name/description */}
                {isEditMode && (
                    <Panel position="top-left" className="bg-surface-1/90 backdrop-blur-2xl border border-white/[0.06] rounded-xl p-3 min-w-[340px] shadow-lg">
                        <div className="text-[9px] uppercase tracking-wider text-text-tertiary mb-2 font-bold">
                            Compositor de Plan
                        </div>
                        <input
                            value={planName}
                            onChange={(e) => useGraphStore.getState().setPlanName(e.target.value)}
                            className="input-field mb-1"
                            placeholder="Nombre del plan"
                        />
                        <input
                            value={planDescription}
                            onChange={(e) => useGraphStore.getState().setPlanDescription(e.target.value)}
                            className="input-field text-[11px]"
                            placeholder="Descripcion"
                        />
                    </Panel>
                )}

                {/* Edit mode: FAB for adding nodes */}
                {isEditMode && (
                    <Panel position="top-right" className="mr-3 mt-3">
                        <button
                            onClick={createManualNode}
                            className="w-10 h-10 rounded-full bg-accent-primary text-white flex items-center justify-center shadow-lg shadow-accent-primary/30 hover:scale-110 active:scale-95 transition-all"
                            title="Anadir nodo"
                        >
                            <Plus size={20} />
                        </button>
                    </Panel>
                )}

                {/* Progress bar */}
                <AnimatePresence>
                    {progressStats && (
                        <Panel position="top-center">
                            <ProgressBar stats={progressStats} />
                        </Panel>
                    )}
                </AnimatePresence>

                {/* Toolbar */}
                <Panel position="bottom-center" className="mb-4">
                    <GraphToolbar
                        onEnterEdit={() => useGraphStore.getState().setEditMode(true)}
                        onExitEdit={() => {
                            useGraphStore.getState().setEditMode(false);
                            fetchGraphData();
                        }}
                        onAddNode={createManualNode}
                        onSaveDraft={handleSaveDraft}
                        onExecute={handleExecute}
                    />
                </Panel>

                {/* Node editor panel */}
                <AnimatePresence>
                    {isEditMode && selectedEditNode && (
                        <Panel position="top-right" className="mt-14">
                            <NodeEditor
                                node={selectedEditNode}
                                models={models}
                                onUpdateField={updateSelectedNodeData}
                                onDelete={deleteSelectedNode}
                            />
                        </Panel>
                    )}
                </AnimatePresence>
            </ReactFlow>
        </div>
    );
};
