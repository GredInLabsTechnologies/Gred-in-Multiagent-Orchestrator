import React, { useState, useCallback, useEffect } from 'react';
import ReactFlow, {
    addEdge,
    Background,
    Controls,
    Node as RFNode,
    useNodesState,
    useEdgesState,
    Panel,
    MarkerType,
    OnConnect,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Plus, Save, Play, Trash2, Settings2, Info } from 'lucide-react';
import { ComposerNode } from './ComposerNode';
import { API_BASE, CustomPlanNode, CustomPlanEdge } from '../types';
import { useToast } from './Toast';

const nodeTypes = {
    custom: ComposerNode,
};

export const PlanComposer: React.FC = () => {
    const { addToast } = useToast();
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [selectedNode, setSelectedNode] = useState<RFNode | null>(null);
    const [planName, setPlanName] = useState('My Custom Plan');
    const [description, setDescription] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [isExecuting, setIsExecuting] = useState(false);
    const [activePlanId, setActivePlanId] = useState<string | null>(null);

    // SSE Listener for real-time updates
    useEffect(() => {
        const eventSource = new EventSource(`${API_BASE}/ops/stream`, { withCredentials: true });

        eventSource.onmessage = (event) => {
            try {
                const { event: eventType, data } = JSON.parse(event.data);
                if (eventType === 'custom_node_status' && data.plan_id === activePlanId) {
                    setNodes((nds) => nds.map((n) => {
                        if (n.id === data.node_id) {
                            return {
                                ...n,
                                data: {
                                    ...n.data,
                                    status: data.status,
                                    output: data.output || n.data.output,
                                    error: data.error || n.data.error
                                }
                            };
                        }
                        return n;
                    }));
                } else if (eventType === 'custom_plan_finished' && data.plan_id === activePlanId) {
                    setIsExecuting(false);
                    addToast(`Plan ${data.status === 'done' ? 'completado' : 'fallido'}`, data.status === 'done' ? 'success' : 'error');
                }
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        };

        return () => eventSource.close();
    }, [activePlanId, setNodes, addToast]);

    // Initial node
    useEffect(() => {
        if (nodes.length === 0) {
            const newNode: RFNode = {
                id: 'node_1',
                type: 'custom',
                position: { x: 250, y: 50 },
                data: {
                    label: 'Initial Task',
                    prompt: 'What should happen first?',
                    model: 'qwen2.5-coder:32b',
                    provider: 'ollama',
                    role: 'worker',
                    status: 'pending'
                },
            };
            setNodes([newNode]);
        }
    }, [nodes.length, setNodes]);

    const onConnect: OnConnect = useCallback((params) => {
        setEdges((eds) => addEdge({
            ...params,
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed, color: '#0a84ff' },
            style: { stroke: '#0a84ff', strokeWidth: 2 }
        }, eds));
    }, [setEdges]);

    const addNode = () => {
        const id = `node_${nodes.length + 1}`;
        const newNode: RFNode = {
            id,
            type: 'custom',
            position: { x: Math.random() * 400, y: Math.random() * 400 },
            data: {
                label: `Task ${nodes.length + 1}`,
                prompt: '',
                model: 'auto',
                provider: 'auto',
                role: 'worker',
                status: 'pending'
            },
        };
        setNodes((nds: RFNode[]) => nds.concat(newNode));
    };

    const deleteNode = () => {
        if (!selectedNode) return;
        setNodes((nds: RFNode[]) => nds.filter((n) => n.id !== selectedNode.id));
        setEdges((eds) => eds.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id));
        setSelectedNode(null);
    };

    const updateNodeData = (field: string, value: any) => {
        if (!selectedNode) return;
        setNodes((nds: RFNode[]) => nds.map((n: RFNode) => {
            if (n.id === selectedNode.id) {
                return { ...n, data: { ...n.data, [field]: value } };
            }
            return n;
        }));
        // Also update local selectedNode to reflect changes in UI
        setSelectedNode((prev) => prev ? { ...prev, data: { ...prev.data, [field]: value } } : null);
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            const planNodes: CustomPlanNode[] = nodes.map((n: RFNode) => ({
                id: n.id,
                label: n.data.label,
                prompt: n.data.prompt,
                model: n.data.model,
                provider: n.data.provider,
                role: n.data.role,
                status: n.data.status,
                position: n.position,
                depends_on: edges.filter(e => e.target === n.id).map(e => e.source),
                config: {}
            }));

            const planEdges: CustomPlanEdge[] = edges.map(e => ({
                id: e.id,
                source: e.source,
                target: e.target
            }));

            const response = await fetch(`${API_BASE}/ops/custom-plans`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: planName,
                    description,
                    nodes: planNodes,
                    edges: planEdges
                }),
                credentials: 'include'
            });

            if (response.ok) {
                const savedPlan = await response.json();
                setActivePlanId(savedPlan.id);
                addToast('Plan guardado exitosamente.', 'success');
            } else {
                throw new Error('Failed to save plan');
            }
        } catch (err) {
            addToast(`Error al guardar: ${err}`, 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const handleExecute = async () => {
        if (!activePlanId) {
            addToast('Primero guarda el plan antes de ejecutar.', 'info');
            return;
        }
        setIsExecuting(true);
        try {
            const response = await fetch(`${API_BASE}/ops/custom-plans/${activePlanId}/execute`, {
                method: 'POST',
                credentials: 'include'
            });
            if (response.ok) {
                addToast('Ejecución iniciada.', 'success');
                // Optional: Poll for updates
            } else {
                addToast('Error al iniciar ejecución.', 'error');
            }
        } catch (err) {
            addToast(`Error en ejecución: ${err}`, 'error');
            setIsExecuting(false);
        }
    };

    const onNodeClick = (_: React.MouseEvent, node: RFNode) => {
        setSelectedNode(node);
    };

    const onPaneClick = () => {
        setSelectedNode(null);
    };

    return (
        <div className="flex flex-col h-full bg-[#0a0a0a] text-[#f5f5f7]">
            {/* Toolbar */}
            <div className="h-16 border-b border-[#2c2c2e] px-6 flex items-center justify-between bg-[#141414]/50 backdrop-blur-md">
                <div className="flex items-center gap-4">
                    <div className="flex flex-col">
                        <input
                            value={planName}
                            onChange={(e) => setPlanName(e.target.value)}
                            className="bg-transparent text-sm font-bold border-none outline-none focus:ring-0 p-0 text-[#f5f5f7] placeholder:text-[#424245]"
                            placeholder="Plan Name"
                        />
                        <input
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            className="bg-transparent text-[10px] border-none outline-none focus:ring-0 p-0 text-[#86868b] placeholder:text-[#424245]"
                            placeholder="Description"
                        />
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#1c1c1e] border border-[#2c2c2e] text-[10px] font-bold uppercase tracking-wider text-[#f5f5f7] hover:bg-[#2c2c2e] transition-all disabled:opacity-50"
                    >
                        {isSaving ? <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Save size={14} />}
                        Save
                    </button>
                    <button
                        onClick={handleExecute}
                        disabled={isExecuting || !activePlanId}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all disabled:opacity-50
                            ${activePlanId ? 'bg-green-500/10 text-green-400 border border-green-500/20 hover:bg-green-500/20' : 'bg-[#1c1c1e] text-[#424245] border border-[#2c2c2e]'}
                        `}
                    >
                        <Play size={14} />
                        Execute
                    </button>
                </div>
            </div>

            <div className="flex-1 flex overflow-hidden">
                {/* Visual Editor */}
                <div className="flex-1 relative">
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onConnect={onConnect}
                        nodeTypes={nodeTypes}
                        onNodeClick={onNodeClick}
                        onPaneClick={onPaneClick}
                        fitView
                        proOptions={{ hideAttribution: true }}
                    >
                        <Background color="#1c1c1e" gap={24} size={1} />
                        <Controls />
                        <Panel position="top-right">
                            <button
                                onClick={addNode}
                                className="w-10 h-10 rounded-full bg-[#0a84ff] text-white flex items-center justify-center shadow-lg shadow-[#0a84ff]/30 hover:scale-110 active:scale-95 transition-all"
                            >
                                <Plus size={20} />
                            </button>
                        </Panel>
                    </ReactFlow>
                </div>

                {/* Properties Panel */}
                <div className={`w-80 border-l border-[#2c2c2e] bg-[#141414]/80 backdrop-blur-xl flex flex-col transition-all
                    ${selectedNode ? 'translate-x-0' : 'translate-x-full absolute right-0'}
                `}>
                    {selectedNode && (
                        <div className="p-6 space-y-6 overflow-y-auto">
                            <div className="flex items-center justify-between">
                                <h3 className="text-xs font-bold uppercase tracking-widest text-[#86868b] flex items-center gap-2">
                                    <Settings2 size={14} />
                                    Node Configuration
                                </h3>
                                <button onClick={deleteNode} className="text-[#ff453a] hover:bg-[#ff453a]/10 p-1 rounded transition-all">
                                    <Trash2 size={16} />
                                </button>
                            </div>

                            <div className="space-y-4">
                                <div className="space-y-1.5">
                                    <label htmlFor="node-label" className="text-[10px] uppercase tracking-widest font-black text-[#424245]">Label</label>
                                    <input
                                        id="node-label"
                                        value={selectedNode.data.label}
                                        onChange={(e) => updateNodeData('label', e.target.value)}
                                        className="w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded-lg px-3 py-2 text-xs text-[#f5f5f7] focus:outline-none focus:ring-1 focus:ring-[#0a84ff]"
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <label htmlFor="node-role" className="text-[10px] uppercase tracking-widest font-black text-[#424245]">Role</label>
                                    <select
                                        id="node-role"
                                        value={selectedNode.data.role}
                                        onChange={(e) => updateNodeData('role', e.target.value)}
                                        className="w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded-lg px-3 py-2 text-xs text-[#f5f5f7] focus:outline-none focus:ring-1 focus:ring-[#0a84ff]"
                                    >
                                        <option value="worker">Worker</option>
                                        <option value="reviewer">Reviewer</option>
                                        <option value="researcher">Researcher</option>
                                    </select>
                                </div>

                                <div className="space-y-1.5">
                                    <label htmlFor="node-model" className="text-[10px] uppercase tracking-widest font-black text-[#424245]">Model / Provider</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        <input
                                            id="node-model"
                                            value={selectedNode.data.model}
                                            onChange={(e) => updateNodeData('model', e.target.value)}
                                            placeholder="Model (auto)"
                                            className="w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded-lg px-3 py-2 text-xs text-[#f5f5f7] focus:outline-none focus:ring-1 focus:ring-[#0a84ff]"
                                        />
                                        <input
                                            value={selectedNode.data.provider}
                                            onChange={(e) => updateNodeData('provider', e.target.value)}
                                            placeholder="Provider (auto)"
                                            className="w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded-lg px-3 py-2 text-xs text-[#f5f5f7] focus:outline-none focus:ring-1 focus:ring-[#0a84ff]"
                                        />
                                    </div>
                                </div>

                                <div className="space-y-1.5">
                                    <label htmlFor="node-prompt" className="text-[10px] uppercase tracking-widest font-black text-[#424245]">Prompt / Instructions</label>
                                    <textarea
                                        id="node-prompt"
                                        value={selectedNode.data.prompt}
                                        onChange={(e) => updateNodeData('prompt', e.target.value)}
                                        rows={8}
                                        className="w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded-lg px-3 py-2 text-xs text-[#f5f5f7] focus:outline-none focus:ring-1 focus:ring-[#0a84ff] resize-none"
                                        placeholder="Enter agent instructions..."
                                    />
                                    <div className="flex items-start gap-2 text-[10px] text-[#86868b] bg-blue-500/5 p-2 rounded border border-blue-500/10">
                                        <Info size={12} className="shrink-0 mt-0.5" />
                                        <span>Outputs from dependency nodes will be automatically injected into the context of this node.</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
