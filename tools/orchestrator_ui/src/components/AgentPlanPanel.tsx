import React from 'react';
import { CheckCircle2, Circle, PlayCircle, XCircle, MessageSquare, ListTodo } from 'lucide-react';
import { AgentPlan, TaskStatus } from '../types';
import { useAgentControl } from '../hooks/useAgentControl';
import { ConfidenceMeter } from './ConfidenceMeter';
import { Wallet } from 'lucide-react';

interface AgentPlanPanelProps {
    plan?: AgentPlan;
    agentId?: string;
}

const StatusIcon = ({ status }: { status: TaskStatus }) => {
    switch (status) {
        case 'done': return <CheckCircle2 size={16} className="text-[#32d74b]" />;
        case 'running': return <PlayCircle size={16} className="text-[#0a84ff] animate-pulse" />;
        case 'failed': return <XCircle size={16} className="text-[#ff3b30]" />;
        default: return <Circle size={16} className="text-[#424245]" />;
    }
};

export const AgentPlanPanel: React.FC<AgentPlanPanelProps> = ({ plan, agentId }) => {
    const { paused, loading, pauseAgent, resumeAgent, cancelPlan } = useAgentControl(agentId ?? null);
    if (!plan) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-[#86868b] text-center px-6">
                <ListTodo size={32} className="mb-4 opacity-20" />
                <p className="text-sm font-medium">Sin plan activo</p>
                <p className="text-[10px] mt-1">Este agente aún no ha generado una estrategia.</p>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-fade-in">
            {/* Task List */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-[#86868b] mb-4">
                    <ListTodo size={14} />
                    <span className="text-[10px] font-bold uppercase tracking-widest">Execution Strategy</span>
                </div>
                <div className="space-y-2">
                    {plan.tasks.map((task, index) => (
                        <div
                            key={task.id}
                            className={`
                                p-3 rounded-xl border transition-all duration-200
                                ${task.status === 'running'
                                    ? 'bg-[#0a84ff]/5 border-[#0a84ff]/20'
                                    : 'bg-[#141414] border-[#1c1c1e]'}
                            `}
                        >
                            <div className="flex items-start gap-3">
                                <div className="mt-0.5">
                                    <StatusIcon status={task.status} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between mb-1">
                                        <span className={`text-[10px] font-mono ${task.status === 'done' ? 'text-[#32d74b]' : 'text-[#86868b]'}`}>
                                            STEP {index + 1}
                                        </span>
                                        {task.status === 'running' && (
                                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-[#0a84ff]/20 text-[#0a84ff] font-bold animate-pulse">
                                                ACTIVE
                                            </span>
                                        )}
                                    </div>
                                    <p className={`text-xs leading-relaxed ${task.status === 'done' ? 'text-[#86868b] line-through opacity-70' : 'text-[#f5f5f7]'}`}>
                                        {task.description}
                                    </p>

                                    {(task.confidence || task.cost_usd) && (
                                        <div className="mt-2 flex items-center gap-3">
                                            {task.confidence && <ConfidenceMeter data={task.confidence} />}
                                            {task.cost_usd && (
                                                <div className="flex items-center gap-1 text-[10px] text-[#32d74b] font-mono">
                                                    <Wallet size={10} />
                                                    ${task.cost_usd.toFixed(4)}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {task.output && (
                                        <div className="mt-2 p-2 rounded-lg bg-[#000000]/50 border border-[#1c1c1e] font-mono text-[10px] text-[#32d74b] opacity-80 overflow-x-auto">
                                            {task.output}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Reasoning Stream */}
            {plan.reasoning && plan.reasoning.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center gap-2 text-[#86868b] mb-4">
                        <MessageSquare size={14} />
                        <span className="text-[10px] font-bold uppercase tracking-widest">Thought Process</span>
                    </div>
                    <div className="bg-[#0a0a0a] border border-[#1c1c1e] rounded-xl overflow-hidden">
                        <div className="p-3 font-mono text-[11px] space-y-2 max-h-[200px] overflow-y-auto custom-scrollbar">
                            {plan.reasoning.map((thought) => (
                                <div key={thought.id} className="flex gap-2 text-[#86868b]">
                                    <span className="text-[#0a84ff] shrink-0">›</span>
                                    <span className="leading-relaxed">{thought.content}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Agent Controls */}
            <div className="pt-4 flex gap-2">
                <button
                    onClick={() => paused ? resumeAgent() : pauseAgent()}
                    disabled={loading}
                    className="flex-1 h-9 rounded-lg bg-[#1c1c1e] border border-[#2c2c2e] text-[11px] font-semibold text-[#f5f5f7] hover:bg-[#2c2c2e] transition-colors disabled:opacity-50"
                >
                    {paused ? 'Resume Agent' : 'Pause Agent'}
                </button>
                <button
                    onClick={() => plan && cancelPlan(plan.id)}
                    disabled={loading || !plan}
                    className="flex-1 h-9 rounded-lg bg-[#ff3b30]/10 border border-[#ff3b30]/20 text-[11px] font-semibold text-[#ff3b30] hover:bg-[#ff3b30]/20 transition-colors disabled:opacity-50"
                >
                    Cancel Plan
                </button>
            </div>
        </div>
    );
};
