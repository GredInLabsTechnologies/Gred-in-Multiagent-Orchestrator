import React from 'react';
import { Bot, Cpu, DollarSign, Terminal } from 'lucide-react';

interface AgentHoverCardProps {
    data: {
        label: string;
        system_prompt?: string;
        agent_config?: {
            model: string;
            role: string;
            goal: string;
        };
        estimated_tokens?: number;
    };
    isVisible: boolean;
}

export const AgentHoverCard: React.FC<AgentHoverCardProps> = ({ data, isVisible }) => {
    if (!isVisible || !data.agent_config) return null;

    const cost = data.estimated_tokens ? (data.estimated_tokens / 1000 * 0.002).toFixed(4) : '0.0000';

    return (
        <div className={`absolute -top-4 left-1/2 -translate-x-1/2 -translate-y-full mb-4 w-72 
            bg-[#1c1c1e]/90 backdrop-blur-xl border border-white/10 rounded-2xl p-4 shadow-2xl z-50
            transition-all duration-300 ease-out origin-bottom
            ${isVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95 pointer-events-none'}`}>

            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="p-1.5 bg-blue-500/20 rounded-lg">
                        <Bot size={16} className="text-blue-400" />
                    </div>
                    <div>
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider">{data.agent_config.role}</h4>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <Cpu size={10} className="text-white/40" />
                            <span className="text-[10px] text-white/40 font-mono">{data.agent_config.model}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="space-y-3">
                <div className="p-2.5 bg-black/40 rounded-xl border border-white/5">
                    <div className="flex items-center gap-1.5 mb-1.5 opacity-60">
                        <Terminal size={10} className="text-blue-400" />
                        <span className="text-[10px] uppercase font-bold tracking-tighter text-blue-400">System Intent</span>
                    </div>
                    <p className="text-[11px] text-white/80 leading-relaxed line-clamp-3 italic">
                        "{data.system_prompt || 'No system prompt defined.'}"
                    </p>
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-white/5">
                    <div className="flex items-center gap-1 text-[10px] text-white/40">
                        <span className="font-mono">{data.estimated_tokens || 0} tokens</span>
                    </div>
                    <div className="flex items-center gap-0.5 px-1.5 py-0.5 bg-emerald-500/10 rounded-md">
                        <DollarSign size={8} className="text-emerald-400" />
                        <span className="text-[10px] font-bold text-emerald-400 font-mono">${cost}</span>
                    </div>
                </div>
            </div>

            {/* Pointer arrow */}
            <div className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-3 h-3 bg-[#1c1c1e] border-r border-b border-white/10 rotate-45" />
        </div>
    );
};
