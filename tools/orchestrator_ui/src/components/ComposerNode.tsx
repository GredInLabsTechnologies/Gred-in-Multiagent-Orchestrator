import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Bot, Cpu, AlertCircle, CheckCircle2, PlayCircle, Clock } from 'lucide-react';

export const ComposerNode = memo(({ data, selected }: NodeProps) => {
    const { label, role, status, model, node_type } = data;

    const typePalette: Record<string, string> = {
        orchestrator: 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40',
        worker: 'bg-blue-500/15 text-blue-300 border-blue-400/40',
        reviewer: 'bg-orange-500/15 text-orange-300 border-orange-400/40',
        researcher: 'bg-purple-500/15 text-purple-300 border-purple-400/40',
        tool: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/40',
        human_gate: 'bg-amber-500/15 text-amber-300 border-amber-400/40',
    };

    const getStatusIcon = () => {
        switch (status) {
            case 'done': return <CheckCircle2 className="text-accent-trust" size={12} />;
            case 'error': return <AlertCircle className="text-accent-alert" size={12} />;
            case 'running': return <PlayCircle className="text-accent-primary animate-pulse" size={12} />;
            default: return <Clock className="text-text-secondary" size={12} />;
        }
    };

    const getRoleIcon = () => {
        switch (role) {
            case 'reviewer': return <CheckCircle2 size={10} />;
            case 'researcher': return <Bot size={10} />;
            default: return <Cpu size={10} />;
        }
    };

    return (
        <div className={`
            min-w-[180px] bg-surface-2 border-2 rounded-xl p-3 shadow-2xl transition-all
            ${selected ? 'border-accent-primary shadow-accent-primary/20' : 'border-border-primary'}
        `}>
            <Handle type="target" position={Position.Left} className="!bg-accent-primary !border-none !w-2 !h-2" />

            <div className="flex items-center justify-between mb-2">
                <div className={`flex items-center gap-1.5 px-1.5 py-0.5 rounded border text-[8px] uppercase font-bold tracking-wider
                    ${typePalette[node_type || role] || typePalette.worker}
                `}>
                    {node_type || role || 'worker'}
                </div>
            </div>

            <div className="flex items-center justify-between mb-2">
                <div className={`flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[8px] uppercase font-bold tracking-wider
                    ${role === 'reviewer' ? 'bg-orange-500/10 text-orange-400' :
                        (role === 'researcher' ? 'bg-purple-500/10 text-purple-400' :
                            'bg-blue-500/10 text-blue-400')}
                `}>
                    {getRoleIcon()}
                    {role}
                </div>
                {getStatusIcon()}
            </div>

            <div className="space-y-1">
                <div className="text-xs font-semibold text-text-primary truncate">{label}</div>
                <div className="text-[10px] text-text-secondary flex items-center gap-1">
                    <span className="font-mono bg-surface-3 px-1 rounded truncate max-w-[120px]">{model || 'auto'}</span>
                </div>
            </div>

            <Handle type="source" position={Position.Right} className="!bg-accent-primary !border-none !w-2 !h-2" />
        </div>
    );
});

ComposerNode.displayName = 'ComposerNode';
