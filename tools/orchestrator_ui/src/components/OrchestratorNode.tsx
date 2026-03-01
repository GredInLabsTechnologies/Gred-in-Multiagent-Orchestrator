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

const getStatusLabel = (status?: string) => {
    switch (status) {
        case 'running': return 'ejecutando';
        case 'done': return 'finalizado';
        case 'failed': return 'fallido';
        case 'doubt': return 'dudas';
        default: return 'esperando';
    }
};

export const OrchestratorNode = memo(({ data }: { data: any }) => {
    const [isHovered, setIsHovered] = useState(false);
    const statusColor = getStatusColor(data.status);
    const statusLabel = getStatusLabel(data.status);

    return (
        <div
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            className={`px-4 py-3 rounded-xl bg-surface-1 border-2 shadow-2xl transition-all min-w-[200px] cursor-default relative ${data.status === 'running' ? 'node-running' : 'border-white/5 hover:border-white/20'}`}
        >
            <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-zinc-600 border-none" />

            <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                    <span className="text-[10px] font-black uppercase tracking-widest text-zinc-500">{data.type || 'Agente'}</span>
                    <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-black/40 border border-white/5 ${statusColor}`}>
                        {statusLabel}
                    </span>
                </div>

                <div className="flex items-center gap-2 group">
                    <h3 className="text-sm font-bold text-white truncate max-w-[140px]">{data.label}</h3>
                    <AgentHoverCard data={data} isVisible={isHovered} />
                </div>

                {data.confidence !== undefined && (
                    <div className="mt-2 space-y-1">
                        <div className="flex justify-between text-[9px] font-bold text-zinc-500 uppercase tracking-tighter">
                            <span>Confianza</span>
                            <span>{Math.round(data.confidence * 100)}%</span>
                        </div>
                        <ConfidenceMeter data={data.confidence} />
                    </div>
                )}

                {data.latest_log && (
                    <div className="mt-2 p-2 rounded-lg bg-black/40 border border-white/5">
                        <p className="text-[9px] font-mono text-zinc-400 line-clamp-2 leading-relaxed italic">
                            {data.latest_log}
                        </p>
                    </div>
                )}
            </div>

            <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-zinc-600 border-none" />
        </div>
    );
});
