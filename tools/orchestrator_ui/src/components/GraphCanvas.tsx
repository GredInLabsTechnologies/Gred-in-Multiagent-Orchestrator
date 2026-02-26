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
    addEdge
} from 'reactflow';
import 'reactflow/dist/style.css';
import { BridgeNode } from './BridgeNode';
import { OrchestratorNode } from './OrchestratorNode';
import { RepoNode } from './RepoNode';
import { ClusterNode } from './ClusterNode';
import { PlanOverlayCard } from './PlanOverlayCard';
import { API_BASE } from '../types';
import { Edit2, Save, X } from 'lucide-react';
import { useToast } from './Toast';

const nodeTypes = {
    bridge: BridgeNode,
    orchestrator: OrchestratorNode,
    repo: RepoNode,
    cluster: ClusterNode,
};

interface GraphCanvasProps {
    onNodeSelect: (nodeId: string | null) => void;
    selectedNodeId: string | null;
    onNodeCountChange?: (count: number) => void;
    onApprovePlan?: (draftId: string) => void;
    onRejectPlan?: (draftId: string) => void;
    onEditPlan?: () => void;
    planLoading?: boolean;
}

export const GraphCanvas: React.FC<GraphCanvasProps> = ({
    onNodeSelect,
    selectedNodeId,
    onNodeCountChange,
    onApprovePlan,
    onRejectPlan,
    onEditPlan,
    planLoading,
}) => {
    const { addToast } = useToast();
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [isEditMode, setIsEditMode] = useState(false);
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

            // Merge server data with user-moved positions
            const nodesWithLiveState = data.nodes.map((n: any) => {
                const userPos = userPositions.current[n.id];
                return {
                    ...n,
                    position: userPos || n.position,
                    data: {
                        ...n.data,
                        status: n.data.status || 'pending',
                        confidence: n.data.confidence,
                        pendingQuestions: n.data.pendingQuestions,
                        plan: n.data.plan,
                        quality: n.data.quality,
                        trustLevel: n.data.trustLevel || 'autonomous'
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
        const actionableNodes = nodes.filter(n => n.data?.status && n.type === 'orchestrator');
        if (actionableNodes.length === 0) return null;

        const doneCount = actionableNodes.filter(n => ['done', 'failed', 'doubt'].includes(n.data.status)).length;
        const total = actionableNodes.length;

        if (!hasRunningNodes && doneCount !== total) return null;
        if (doneCount === total && !hasRunningNodes) return null;

        return { done: doneCount, total, percent: Math.round((doneCount / total) * 100) };
    }, [nodes, hasRunningNodes]);

    const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
        onNodeSelect(node.id);
    }, [onNodeSelect]);

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
            type: 'orchestrator',
            position,
            data: { label: 'Nodo Manual', status: 'pending', trustLevel: 'supervised' },
        };

        setNodes((nds) => nds.concat(newNode));
        addToast('Nodo manual creado', 'info');
    }, [project, setNodes, addToast]);

    const onPaneClick = useCallback((event: React.MouseEvent) => {
        if (isEditMode) {
            if (event.detail >= 2) {
                createManualNodeAtClientPoint(event);
            }
            return;
        }

        onNodeSelect(null);
    }, [isEditMode, onNodeSelect, createManualNodeAtClientPoint]);

    const onConnect = useCallback((params: Connection) => {
        if (isEditMode && params.source && params.target) {
            setEdges((eds) => addEdge({ ...params, animated: true, style: { stroke: 'var(--status-pending)', strokeWidth: 2 } }, eds));
        }
    }, [isEditMode, setEdges]);

    const handleSaveDraft = useCallback(async () => {
        if (nodes.length === 0) {
            addToast('No hay nodos para guardar en borrador manual', 'error');
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/ops/drafts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: `Edición manual de grafo (${new Date().toLocaleString()})`,
                    context: {
                        manual_graph: {
                            nodes: nodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.data })),
                            edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target }))
                        }
                    }
                }),
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            setIsEditMode(false);
            addToast('Borrador manual guardado', 'success');
            await fetchGraphData();
        } catch (error) {
            addToast('No se pudo guardar el borrador manual', 'error');
        }
    }, [nodes, edges, addToast, fetchGraphData]);

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
                        if (node.type === 'orchestrator') return 'var(--status-running)';
                        if (node.type === 'bridge') return 'var(--status-running)';
                        if (node.type === 'repo') return 'var(--accent-purple)';
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
                        Grafo de Orquestación
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
                    <div className="flex bg-surface-2/90 backdrop-blur-xl rounded-full border border-border-primary p-1.5 shadow-xl">
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
                                <div className="px-3 py-1 text-[10px] text-text-secondary flex items-center">
                                    Doble click en canvas = crear nodo · arrastra handles = crear edge
                                </div>
                                <button
                                    onClick={handleSaveDraft}
                                    className="flex items-center gap-2 px-4 py-2 bg-accent-trust/10 text-accent-trust hover:bg-accent-trust/20 rounded-full transition-colors text-[11px] font-bold tracking-wide mr-1"
                                >
                                    <Save size={14} />
                                    Guardar Borrador
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
            </ReactFlow>
        </div>
    );
};
