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
                console.error(`Graph fetch error: ${response.status}`);
                onNodeCountChange?.(0);
                return;
            }

            const data = await response.json();

            const formattedEdges = data.edges.map((e: any) => ({
                ...e,
                animated: true,
                style: {
                    stroke: e.style?.stroke || (e.source === 'tunnel' ? '#0a84ff' : '#32d74b'),
                    strokeWidth: e.style?.strokeWidth || 2,
                },
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: e.style?.stroke || (e.source === 'tunnel' ? '#0a84ff' : '#32d74b'),
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
            console.error('Error fetching graph data:', error);
            onNodeCountChange?.(0);
        }
    }, [setNodes, setEdges, onNodeCountChange]);

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

    const onPaneClick = useCallback((event: React.MouseEvent) => {
        if (isEditMode) {
            const target = event.target as HTMLElement;
            const reactFlowBounds = target.closest('.react-flow')?.getBoundingClientRect();
            if (reactFlowBounds) {
                const position = project({
                    x: event.clientX - reactFlowBounds.left,
                    y: event.clientY - reactFlowBounds.top,
                });
                const newNode = {
                    id: `manual_${Date.now()}`,
                    type: 'orchestrator',
                    position,
                    data: { label: 'Nodo Manual', status: 'pending' },
                };
                setNodes((nds) => nds.concat(newNode));
            }
        } else {
            onNodeSelect(null);
        }
    }, [isEditMode, project, setNodes, onNodeSelect]);

    const onConnect = useCallback((params: Connection) => {
        if (isEditMode) {
            setEdges((eds) => addEdge({ ...params, animated: true, style: { stroke: '#86868b', strokeWidth: 2 } }, eds));
        }
    }, [isEditMode, setEdges]);

    const handleSaveDraft = async () => {
        try {
            await fetch(`${API_BASE}/ops/drafts`, {
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
            setIsEditMode(false);
        } catch (error) {
            console.error('Failed to save manual draft:', error);
        }
    };

    return (
        <div className="w-full h-full bg-[#0a0a0a]">
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
                <Background color="#1c1c1e" gap={24} size={1} />
                <Controls showInteractive={false} />
                <MiniMap
                    nodeColor={(node) => {
                        if (node.type === 'orchestrator') return '#0a84ff';
                        if (node.type === 'bridge') return '#0a84ff';
                        if (node.type === 'repo') return '#5e5ce6';
                        return '#86868b';
                    }}
                    maskColor="rgba(0, 0, 0, 0.7)"
                    className="!bg-[#0a0a0a] !border-[#2c2c2e] !rounded-xl"
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
                        className="bg-[#141414]/90 backdrop-blur-xl px-3 py-1.5 rounded-lg border border-[#2c2c2e] text-[10px] text-[#86868b] font-mono uppercase tracking-wider"
                    >
                        Grafo de Orquestación
                    </Panel>
                )}

                {progressStats && (
                    <Panel position="top-center" className="bg-[#141414]/90 backdrop-blur-xl px-4 py-2 rounded-xl border border-[#2c2c2e] min-w-[200px] shadow-lg">
                        <div className="flex justify-between items-center mb-1.5">
                            <span className="text-[10px] text-[#f5f5f7] font-semibold uppercase tracking-wider flex items-center gap-1.5">
                                <div className="w-1.5 h-1.5 rounded-full bg-[#0a84ff] animate-pulse" />
                                Ejecución en progreso
                            </span>
                            <span className="text-[10px] text-[#86868b] font-mono">
                                {progressStats.done} / {progressStats.total}
                            </span>
                        </div>
                        <div className="h-1 w-full bg-[#1c1c1e] rounded-full overflow-hidden">
                            <div
                                className="h-full bg-[#0a84ff] transition-all duration-500 ease-out"
                                style={{ width: `${progressStats.percent}%` }}
                            />
                        </div>
                    </Panel>
                )}

                {/* Edit Mode Toolbar */}
                <Panel position="bottom-center" className="mb-4">
                    <div className="flex bg-[#141414]/90 backdrop-blur-xl rounded-full border border-[#2c2c2e] p-1.5 shadow-xl">
                        {!isEditMode ? (
                            <button
                                onClick={() => setIsEditMode(true)}
                                className="flex items-center gap-2 px-4 py-2 hover:bg-[#1c1c1e] text-[#86868b] hover:text-[#f5f5f7] rounded-full transition-colors text-[11px] font-medium"
                            >
                                <Edit2 size={14} />
                                Modo Edición
                            </button>
                        ) : (
                            <>
                                <button
                                    onClick={handleSaveDraft}
                                    className="flex items-center gap-2 px-4 py-2 bg-[#32d74b]/10 text-[#32d74b] hover:bg-[#32d74b]/20 rounded-full transition-colors text-[11px] font-bold tracking-wide mr-1"
                                >
                                    <Save size={14} />
                                    Guardar Borrador
                                </button>
                                <button
                                    onClick={() => {
                                        setIsEditMode(false);
                                        fetchGraphData(); // reload normal graph
                                    }}
                                    className="flex items-center justify-center w-8 h-8 hover:bg-[#ff453a]/10 text-[#86868b] hover:text-[#ff453a] rounded-full transition-colors"
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
