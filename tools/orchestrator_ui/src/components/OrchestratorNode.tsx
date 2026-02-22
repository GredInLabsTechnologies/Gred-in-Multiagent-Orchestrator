import { memo, useState } from 'react';
import { Handle, Position } from 'reactflow';
import { ConfidenceMeter } from './ConfidenceMeter';
import { AgentHoverCard } from './AgentHoverCard';

const getStatusColor = (status?: string) => {
    switch (status) {
        case 'running': return 'text-blue-400';
        case 'done': return 'text-emerald-400';
        case 'failed': return 'text-rose-400';
        case 'doubt': return 'text-amber-400';
        default: return 'text-white/40';
    }
};

export const OrchestratorNode = memo(({ data, selected }: any) => {
    const [isHovered, setIsHovered] = useState(false);
    const isDoubt = data.status === 'doubt';

    return (
        <div
            className={`group relative px-5 py-4 rounded-2xl bg-[#141414]/90 backdrop-blur-md border-[1.5px] transition-all duration-300
                ${selected ? 'border-blue-500 shadow-[0_0_20px_rgba(59,130,246,0.3)] scale-[1.02]' : 'border-white/10 hover:border-white/20'}`}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
        >
            <AgentHoverCard data={data} isVisible={isHovered} />

            <div className="flex items-center gap-4">
                <div className={`w-2 h-2 rounded-full ${data.status === 'running' ? 'bg-blue-400 animate-pulse' : 'bg-white/20'}`} />
                <div>
                    <div className="text-sm font-bold text-[#f5f5f7] tracking-tight">{data.label}</div>
                    <div className="flex items-center gap-2 mt-1">
                        <div className={`text-[9px] uppercase tracking-widest font-black font-mono ${getStatusColor(data.status)}`}>
                            {isDoubt ? 'DUDAS' : (data.status || 'PENDING')}
                        </div>
                        {data.confidence && <ConfidenceMeter data={data.confidence} />}
                    </div>
                </div>
            </div>

            {/* Quality & Meta indicators */}
            {data.agent_config && (
                <div className="mt-3 pt-3 border-t border-white/5 flex items-center justify-between gap-4">
                    <div className="text-[10px] text-white/30 font-medium truncate max-w-[100px]">
                        {data.agent_config.role}
                    </div>
                    {data.estimated_tokens && (
                        <div className="text-[10px] text-blue-400/60 font-mono whitespace-nowrap">
                            {data.estimated_tokens}t
                        </div>
                    )}
                </div>
            )}

            <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-blue-500 !border-0 -translate-x-1" />
            <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-blue-500 !border-0 translate-x-1" />
        </div>
    );
});
