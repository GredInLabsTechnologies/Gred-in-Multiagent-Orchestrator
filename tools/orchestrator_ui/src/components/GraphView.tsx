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
            const response = await fetch(`${API_BASE}/ui/graph`, {
                credentials: 'include',
            });
            if (!response.ok) return;
            const data = await response.json();

            const formattedEdges = data.edges.map((e: any) => ({
                ...e,
                style: { stroke: e.source === 'tunnel' ? '#0a84ff' : '#32d74b', strokeWidth: 2 },
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: e.source === 'tunnel' ? '#0a84ff' : '#32d74b',
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
        <div className="w-full h-[600px] bg-[#1c1c1e] rounded-2xl overflow-hidden shadow-2xl border border-[#38383a]">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                fitView
            >
                <Background color="#38383a" gap={20} />
                <Controls showInteractive={false} className="bg-[#2c2c2e] fill-white border-[#38383a]" />
                <Panel position="top-left" className="bg-[#2c2c2e] p-2 rounded-md border border-[#38383a] text-xs text-[#86868b] backdrop-blur-md bg-opacity-80">
                    Live Orchestration Graph
                </Panel>
            </ReactFlow>
        </div>
    );
};
