import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Bot, Cpu, AlertCircle, CheckCircle2, PlayCircle, Clock } from 'lucide-react';

export const ComposerNode = memo(({ data, selected }: NodeProps) => {
    const { label, role, status, model } = data;

    const getStatusIcon = () => {
        switch (status) {
            case 'done': return <CheckCircle2 className="text-[#32d74b]" size={12} />;
            case 'error': return <AlertCircle className="text-[#ff453a]" size={12} />;
            case 'running': return <PlayCircle className="text-[#0a84ff] animate-pulse" size={12} />;
            default: return <Clock className="text-[#86868b]" size={12} />;
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
            min-w-[180px] bg-[#1c1c1e] border-2 rounded-xl p-3 shadow-2xl transition-all
            ${selected ? 'border-[#0a84ff] shadow-[#0a84ff]/20' : 'border-[#2c2c2e]'}
        `}>
            <Handle type="target" position={Position.Top} className="!bg-[#0a84ff] !border-none !w-2 !h-2" />

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
                <div className="text-xs font-semibold text-[#f5f5f7] truncate">{label}</div>
                <div className="text-[10px] text-[#86868b] flex items-center gap-1">
                    <span className="font-mono bg-[#2c2c2e] px-1 rounded truncate max-w-[120px]">{model || 'auto'}</span>
                </div>
            </div>

            <Handle type="source" position={Position.Bottom} className="!bg-[#0a84ff] !border-none !w-2 !h-2" />
        </div>
    );
});

ComposerNode.displayName = 'ComposerNode';
