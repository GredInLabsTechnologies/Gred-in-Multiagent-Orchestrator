import React, { useEffect, useCallback, useMemo, useRef } from 'react';
import ReactFlow, {
    Background,
    Controls,
    MiniMap,
    Panel,
    useNodesState,
    useEdgesState,
    MarkerType,
    NodeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { BridgeNode } from './BridgeNode';
import { OrchestratorNode } from './OrchestratorNode';
import { RepoNode } from './RepoNode';
import { ClusterNode } from './ClusterNode';
import { PlanOverlayCard } from './PlanOverlayCard';

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
    const hasFitView = useRef(false);
    const userPositions = useRef<Record<string, { x: number; y: number }>>({});
    const prevNodeIds = useRef<string>('');

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
            const response = await fetch('/ui/graph', {
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

    useEffect(() => {
        fetchGraphData();
        const interval = setInterval(fetchGraphData, 5000);
        return () => clearInterval(interval);
    }, [fetchGraphData]);

    const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
        onNodeSelect(node.id);
    }, [onNodeSelect]);

    const onPaneClick = useCallback(() => {
        onNodeSelect(null);
    }, [onNodeSelect]);

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
                        Live Orchestration Graph
                    </Panel>
                )}
            </ReactFlow>
        </div>
    );
};
