import React, { useMemo, useState } from 'react';
import { X, Activity, Terminal, Settings, ListChecks } from 'lucide-react';
import { AgentPlanPanel } from './AgentPlanPanel';
import { TrustBadge } from './TrustBadge';
import { AgentQuestionCard } from './AgentQuestionCard';
import { QualityAlertPanel } from './QualityAlertPanel';
import AgentChat from './AgentChat';
import { SubAgentCluster } from './SubAgentCluster';
import { useNodes } from 'reactflow';
import { GraphNode, TrustLevel, API_BASE, ORCH_TOKEN } from '../types';
import { SystemPromptEditor } from './SystemPromptEditor';

interface InspectPanelProps {
    selectedNodeId: string | null;
    onClose: () => void;
}

export const InspectPanel: React.FC<InspectPanelProps> = ({
    selectedNodeId,
    onClose,
}) => {
    const nodes = useNodes();
    const selectedNode = useMemo(() =>
        nodes.find(n => n.id === selectedNodeId) as GraphNode | undefined,
        [nodes, selectedNodeId]);

    const planData = selectedNode?.data?.plan;
    const qualityData = selectedNode?.data?.quality;

    const [view, setView] = useState<'overview' | 'plan' | 'quality' | 'chat' | 'delegation' | 'prompt' | 'config'>('overview');

    const handleSavePrompt = async (newPrompt: string) => {
        if (!selectedNodeId || !selectedNode?.data?.plan?.draft_id) return;
        const draftId = selectedNode.data.plan.draft_id;

        try {
            // 1. Fetch current draft to get full plan content
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                headers: { 'Authorization': `Bearer ${ORCH_TOKEN}` }
            });
            if (!resp.ok) throw new Error('Failed to fetch draft');
            const draft = await resp.json();

            // 2. Update the specific task's system prompt in the content
            const plan = JSON.parse(draft.content);
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) {
                task.agent_assignee.system_prompt = newPrompt;
            }

            // 3. Save back to server
            const saveResp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${ORCH_TOKEN}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: JSON.stringify(plan, null, 2)
                })
            });

            if (!saveResp.ok) throw new Error('Failed to save draft');
            console.log('Prompt saved successfully');
        } catch (err) {
            console.error('Error saving prompt:', err);
            alert('Failed to save prompt: ' + (err instanceof Error ? err.message : String(err)));
        }
    };

    const handleModelChange = async (newModel: string) => {
        if (!selectedNodeId || !selectedNode?.data?.plan?.draft_id) return;
        const draftId = selectedNode.data.plan.draft_id;

        try {
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                headers: { 'Authorization': `Bearer ${ORCH_TOKEN}` }
            });
            const draft = await resp.json();
            const plan = JSON.parse(draft.content);
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) {
                task.agent_assignee.model = newModel;
            }

            await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${ORCH_TOKEN}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: JSON.stringify(plan, null, 2)
                })
            });
            console.log('Model updated successfully');
        } catch (err) {
            console.error('Error updating model:', err);
        }
    };

    return (
        <aside className="w-[380px] bg-[#0a0a0a] border-l border-[#2c2c2e] flex flex-col shrink-0 overflow-hidden shadow-2xl z-40">
            <div className="h-12 px-4 flex items-center justify-between border-b border-[#1c1c1e] shrink-0 bg-[#000000]/50">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs font-semibold text-[#f5f5f7] truncate uppercase tracking-wider">
                        {`Node: ${selectedNode?.data?.label || selectedNodeId}`}
                    </span>
                    {selectedNode?.data?.trustLevel && (
                        <TrustBadge level={selectedNode.data.trustLevel} />
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-[#86868b] hover:text-[#f5f5f7] hover:bg-[#1c1c1e] transition-all"
                >
                    <X size={14} />
                </button>
            </div>

            <div className="flex px-4 pt-4 gap-4 border-b border-[#1c1c1e] bg-[#000000]/20 overflow-x-auto no-scrollbar">
                <button
                    onClick={() => setView('prompt')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'prompt' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <Terminal size={12} />
                    Prompt
                    {view === 'prompt' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('config')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'config' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <Settings size={12} />
                    Config
                    {view === 'config' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('plan')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'plan' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <ListChecks size={12} />
                    Plan
                    {view === 'plan' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('overview')}
                    className={`pb-2 shrink-0 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'overview' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    Info
                    {view === 'overview' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-6">
                {selectedNodeId ? (
                    <>
                        {selectedNode?.data?.pendingQuestions && selectedNode.data.pendingQuestions.length > 0 && (
                            <div className="space-y-3 mb-6">
                                {selectedNode.data.pendingQuestions.map(q => (
                                    <AgentQuestionCard
                                        key={q.id}
                                        question={q}
                                        onAnswer={(id: string, ans: string) => console.log('Answered', id, ans)}
                                        onDismiss={(id: string) => console.log('Dismissed', id)}
                                    />
                                ))}
                            </div>
                        )}

                        {view === 'plan' && <AgentPlanPanel plan={planData} />}
                        {view === 'prompt' && (
                            <SystemPromptEditor
                                initialPrompt={selectedNode?.data?.system_prompt || ''}
                                onSave={handleSavePrompt}
                                onReset={() => console.log('Reset prompt')}
                            />
                        )}
                        {view === 'config' && (
                            <div className="space-y-6 animate-fade-in">
                                <div className="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-4">
                                    <div className="flex items-center gap-2 text-white/40 mb-2">
                                        <Settings size={14} />
                                        <span className="text-[10px] font-bold uppercase tracking-widest">Agent Tuning</span>
                                    </div>

                                    <div className="space-y-2">
                                        <label htmlFor="node-model-select" className="text-[10px] font-bold text-white/30 uppercase">Primary Model</label>
                                        <select
                                            id="node-model-select"
                                            className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-blue-100/80 focus:outline-none focus:border-blue-500/50"
                                            value={selectedNode?.data?.agent_config?.model || 'auto'}
                                            onChange={(e) => handleModelChange(e.target.value)}
                                        >
                                            <option value="auto" className="text-amber-400">⚡ Auto (Orchestrator selects)</option>
                                            <optgroup label="— Ollama (Local) —">
                                                <option value="qwen2.5-coder:3b">qwen2.5-coder:3b · fast · local</option>
                                                <option value="qwen2.5-coder:32b">qwen2.5-coder:32b · smart · local</option>
                                                <option value="llama3.2:3b">llama3.2:3b · fast · local</option>
                                                <option value="llama3.1:70b">llama3.1:70b · powerful · local</option>
                                                <option value="mistral:7b">mistral:7b · balanced · local</option>
                                            </optgroup>
                                            <optgroup label="— OpenAI —">
                                                <option value="gpt-4o">gpt-4o · best reasoning</option>
                                                <option value="gpt-4o-mini">gpt-4o-mini · cheap · fast</option>
                                                <option value="gpt-4-turbo">gpt-4-turbo</option>
                                            </optgroup>
                                            <optgroup label="— Anthropic Claude —">
                                                <option value="claude-3-5-sonnet">claude-3-5-sonnet · best overall</option>
                                                <option value="claude-3-haiku">claude-3-haiku · fast · cheap</option>
                                                <option value="claude-3-opus">claude-3-opus · most powerful</option>
                                            </optgroup>
                                            <optgroup label="— Codex —">
                                                <option value="codex-davinci">codex-davinci · code specialist</option>
                                                <option value="codex-cushman">codex-cushman · fast code</option>
                                            </optgroup>
                                            <optgroup label="— Other —">
                                                <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                                                <option value="gemini-1.5-flash">gemini-1.5-flash · fast</option>
                                                <option value="mistral-large">mistral-large</option>
                                                <option value="llama-3.1-70b">llama-3.1-70b (hosted)</option>
                                            </optgroup>
                                        </select>
                                        {(selectedNode?.data?.agent_config?.model === 'auto' || !selectedNode?.data?.agent_config?.model) && (
                                            <p className="text-[9px] text-amber-400/70 leading-relaxed">
                                                The orchestrator will auto-select the most efficient model for this task.
                                            </p>
                                        )}
                                    </div>

                                    <div className="space-y-2">
                                        <label htmlFor="node-role-input" className="text-[10px] font-bold text-white/30 uppercase">Role Definition</label>
                                        <input
                                            id="node-role-input"
                                            type="text"
                                            value={selectedNode?.data?.agent_config?.role || ''}
                                            className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-blue-100/80 focus:outline-none focus:border-blue-500/50"
                                            readOnly
                                        />
                                    </div>

                                    <div className="pt-2">
                                        <button className="w-full py-2 bg-blue-600/10 border border-blue-500/20 rounded-xl text-[10px] font-bold text-blue-400 hover:bg-blue-600/20 transition-all">
                                            SWAP AGENT INHERITANCE
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                        {view === 'quality' && <QualityAlertPanel quality={qualityData} />}
                        {view === 'delegation' && <SubAgentCluster agentId={selectedNodeId} />}
                        {view === 'chat' && <div className="h-[400px]"><AgentChat agentId={selectedNodeId} /></div>}
                        {view === 'overview' && (
                            <div className="space-y-4 animate-fade-in">
                                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                                    <div className="text-[10px] text-white/30 font-bold uppercase tracking-widest mb-3">Node Properties</div>
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center text-xs">
                                            <span className="text-white/40">Type</span>
                                            <span className="text-white/80 font-mono bg-white/5 px-1.5 py-0.5 rounded">{selectedNode?.type}</span>
                                        </div>
                                        <div className="flex justify-between items-center text-xs">
                                            <span className="text-white/40">Status</span>
                                            <span className="text-emerald-400 font-mono">{selectedNode?.data?.status || 'pending'}</span>
                                        </div>
                                        {selectedNode?.data?.estimated_tokens && (
                                            <div className="flex justify-between items-center text-xs">
                                                <span className="text-white/40">Tokens Est.</span>
                                                <span className="text-blue-400 font-mono">{selectedNode.data.estimated_tokens}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {(selectedNode?.type === 'orchestrator' || selectedNode?.type === 'bridge') && (
                                    <div className="p-4 rounded-xl bg-white/5 border border-white/10 space-y-3">
                                        <div className="text-[10px] text-white/30 font-bold uppercase tracking-widest">Delegation Trust</div>
                                        <div className="grid grid-cols-3 gap-2">
                                            {(['autonomous', 'supervised', 'restricted'] as TrustLevel[]).map(level => (
                                                <button
                                                    key={level}
                                                    onClick={() => console.log('Update trust', level)}
                                                    className={`
                                                        flex flex-col items-center gap-1.5 p-2 rounded-lg border transition-all
                                                        ${selectedNode.data.trustLevel === level
                                                            ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                                                            : 'bg-black/20 border-transparent text-white/20 hover:text-white/40'}
                                                    `}
                                                >
                                                    <TrustBadge level={level} size={10} />
                                                    <span className="text-[8px] font-bold truncate capitalize">{level}</span>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex flex-col items-center justify-center py-20 text-white/10 text-center px-6">
                        <Activity size={32} className="mb-4 opacity-10" />
                        <p className="text-sm font-medium">No node selected</p>
                        <p className="text-[10px] mt-1">Select an agent or component to inspect its live state</p>
                    </div>
                )}
            </div>
        </aside>
    );
};
