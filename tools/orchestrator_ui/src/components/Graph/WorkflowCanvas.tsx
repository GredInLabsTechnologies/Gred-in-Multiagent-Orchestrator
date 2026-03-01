import { useCallback, useEffect } from 'react';
import ReactFlow, {
    Background,
    Controls,
    useNodesState,
    useEdgesState,
    addEdge,
    Connection,
    Edge,
    Node,
    Position,
    BackgroundVariant,
    ReactFlowProvider,
    useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { GenericNode, GenericNodeData } from './GenericNode';

const nodeTypes = {
    generic: GenericNode,
    agent_task: GenericNode,
    human_review: GenericNode,
    contract_check: GenericNode,
};

type AppNode = Node<GenericNodeData>;

const getLayoutedElements = (nodes: AppNode[], edges: Edge[]) => {
    const spacingX = 280;
    const spacingY = 140;
    const perRow = 4;

    const layoutedNodes = nodes.map((node, index) => {
        const row = Math.floor(index / perRow);
        const col = index % perRow;
        return {
            ...node,
            targetPosition: Position.Left,
            sourcePosition: Position.Right,
            position: node.position ?? {
                x: col * spacingX,
                y: row * spacingY,
            },
        };
    });

    return { nodes: layoutedNodes, edges };
};

interface WorkflowCanvasProps {
    data: {
        nodes: AppNode[];
        edges: Edge[];
    };
    onNodeClick?: (event: React.MouseEvent, node: Node) => void;
}

interface LayoutHandlerProps {
    nodes: AppNode[];
    edges: Edge[];
    setNodes: (nodes: AppNode[]) => void;
    setEdges: (edges: Edge[]) => void;
}

const LayoutHandler = ({ nodes, edges, setNodes, setEdges }: LayoutHandlerProps) => {
    const { fitView } = useReactFlow();

    useEffect(() => {
        if (nodes.length > 0) {
            const layouted = getLayoutedElements(nodes, edges);
            setNodes([...layouted.nodes]);
            setEdges([...layouted.edges]);
            window.requestAnimationFrame(() => fitView({ padding: 0.2 }));
        }
    }, [nodes.length, edges.length, fitView, setNodes, setEdges]);

    return null;
};

export const WorkflowCanvas = ({ data, onNodeClick }: WorkflowCanvasProps) => {
    const [nodes, setNodes, onNodesChange] = useNodesState(data.nodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(data.edges);

    useEffect(() => {
        setNodes(data.nodes);
        setEdges(data.edges);
    }, [data, setNodes, setEdges]);

    const onConnect = useCallback(
        (params: Connection) => setEdges((eds: Edge[]) => addEdge(params, eds)),
        [setEdges],
    );

    return (
        <div className="w-full h-full bg-zinc-950">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                nodeTypes={nodeTypes}
                proOptions={{ hideAttribution: true }}
                defaultEdgeOptions={{
                    animated: true,
                    style: { stroke: 'var(--accent-primary)', strokeWidth: 2 },
                    type: 'smoothstep'
                }}
            >
                <Background
                    variant={BackgroundVariant.Dots}
                    gap={20}
                    size={1}
                    color="var(--surface-2)"
                />
                <Controls className="!bg-zinc-900 !border-white/10 !fill-zinc-400" />
                <LayoutHandler
                    nodes={nodes}
                    edges={edges}
                    setNodes={setNodes}
                    setEdges={setEdges}
                />
            </ReactFlow>
        </div>
    );
};

export const WorkflowCanvasWrapper = (props: WorkflowCanvasProps) => (
    <ReactFlowProvider>
        <WorkflowCanvas {...props} />
    </ReactFlowProvider>
);
