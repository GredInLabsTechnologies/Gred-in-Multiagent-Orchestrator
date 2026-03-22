import { useEffect, useCallback } from 'react';
import ReactFlow, {
    Background,
    Controls,
    Panel,
    useNodesState,
    useEdgesState,
    MarkerType
} from 'reactflow';
import 'reactflow/dist/style.css';
import { BridgeNode } from './BridgeNode';
import { OrchestratorNode } from './OrchestratorNode';
import { RepoNode } from './RepoNode';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

const nodeTypes = {
    bridge: BridgeNode,
    orchestrator: OrchestratorNode,
    repo: RepoNode,
};

export const GraphView = () => {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);

    const fetchGraphData = useCallback(async () => {
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/graph`, {
                credentials: 'include',
            });
            if (!response.ok) return;
            const data = await response.json();

            const formattedEdges = data.edges.map((e: any) => ({
                ...e,
                style: { stroke: e.source === 'tunnel' ? 'var(--accent-primary)' : 'var(--accent-trust)', strokeWidth: 2 },
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: e.source === 'tunnel' ? 'var(--accent-primary)' : 'var(--accent-trust)',
                },
            }));

            setNodes(data.nodes);
            setEdges(formattedEdges);
        } catch (error) {
            console.error('Error fetching graph data:', error);
        }
    }, [setNodes, setEdges]);

    useEffect(() => {
        fetchGraphData();
        const interval = setInterval(fetchGraphData, 5000);
        return () => clearInterval(interval);
    }, [fetchGraphData]);

    return (
        <div className="w-full h-[600px] bg-surface-2 rounded-2xl overflow-hidden shadow-2xl border border-surface-3">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                fitView
            >
                <Background color="var(--surface-3)" gap={20} />
                <Controls showInteractive={false} className="bg-surface-3 fill-white border-surface-3" />
                <Panel position="top-left" className="bg-surface-3 p-2 rounded-md border border-surface-3 text-xs text-text-secondary backdrop-blur-md bg-opacity-80">
                    Live Orchestration Graph
                </Panel>
            </ReactFlow>
        </div>
    );
};
