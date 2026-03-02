import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import {
    Bot,
    Cpu,
    AlertCircle,
    CheckCircle2,
    PlayCircle,
    Clock,
    Shield,
    Search,
    Wrench,
    UserCheck,
} from 'lucide-react';

/* ── Color system per node type ────────────────────── */

const TYPE_COLORS: Record<string, { accent: string; bg: string; border: string; glow: string }> = {
    orchestrator: {
        accent: '#22d3ee',
        bg: 'bg-cyan-500/8',
        border: 'border-l-cyan-400',
        glow: 'shadow-cyan-500/20',
    },
    worker: {
        accent: '#60a5fa',
        bg: 'bg-blue-500/8',
        border: 'border-l-blue-400',
        glow: 'shadow-blue-500/20',
    },
    reviewer: {
        accent: '#fb923c',
        bg: 'bg-orange-500/8',
        border: 'border-l-orange-400',
        glow: 'shadow-orange-500/20',
    },
    researcher: {
        accent: '#c084fc',
        bg: 'bg-purple-500/8',
        border: 'border-l-purple-400',
        glow: 'shadow-purple-500/20',
    },
    tool: {
        accent: '#34d399',
        bg: 'bg-emerald-500/8',
        border: 'border-l-emerald-400',
        glow: 'shadow-emerald-500/20',
    },
    human_gate: {
        accent: '#fbbf24',
        bg: 'bg-amber-500/8',
        border: 'border-l-amber-400',
        glow: 'shadow-amber-500/20',
    },
};

const DEFAULT_COLORS = TYPE_COLORS.worker;

/* ── Status system ─────────────────────────────────── */

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
    done: { icon: CheckCircle2, color: 'text-emerald-400', label: 'Completado' },
    error: { icon: AlertCircle, color: 'text-red-400', label: 'Error' },
    failed: { icon: AlertCircle, color: 'text-red-400', label: 'Fallido' },
    running: { icon: PlayCircle, color: 'text-blue-400', label: 'Ejecutando' },
    doubt: { icon: Shield, color: 'text-amber-400', label: 'Dudas' },
    pending: { icon: Clock, color: 'text-white/30', label: 'Pendiente' },
};

/* ── Role icons ────────────────────────────────────── */

function getRoleIcon(role: string) {
    switch (role) {
        case 'orchestrator':
            return <Cpu size={11} />;
        case 'reviewer':
            return <CheckCircle2 size={11} />;
        case 'researcher':
            return <Search size={11} />;
        case 'tool':
            return <Wrench size={11} />;
        case 'human_gate':
            return <UserCheck size={11} />;
        default:
            return <Bot size={11} />;
    }
}

/* ── Component ─────────────────────────────────────── */

export const ComposerNode = memo(({ data, selected }: NodeProps) => {
    const { label, status, model, node_type, role, error: nodeError, output } = data;
    const nodeType = node_type || role || 'worker';
    const colors = TYPE_COLORS[nodeType] || DEFAULT_COLORS;
    const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
    const StatusIcon = statusCfg.icon;
    const isRunning = status === 'running';
    const isError = status === 'error' || status === 'failed';
    const isDone = status === 'done';

    return (
        <div
            className={`
                relative min-w-[190px] max-w-[240px] rounded-xl
                border-l-[3px] border border-white/[0.06]
                ${colors.border}
                ${colors.bg}
                bg-surface-2/90 backdrop-blur-lg
                shadow-lg ${selected ? colors.glow : 'shadow-black/20'}
                transition-all duration-200
                ${selected ? 'ring-1 ring-white/20 scale-[1.02]' : ''}
                ${isRunning ? 'node-running' : ''}
            `}
        >
            {/* Running shimmer overlay */}
            {isRunning && (
                <div className="absolute inset-0 rounded-xl overflow-hidden pointer-events-none">
                    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.04] to-transparent animate-shimmer" />
                </div>
            )}

            {/* Handles */}
            <Handle
                type="target"
                position={Position.Left}
                className="!w-3 !h-3 !bg-surface-3 !border-2 !border-white/20 hover:!border-accent-primary hover:!bg-accent-primary/20 !-left-1.5 transition-all"
            />
            <Handle
                type="source"
                position={Position.Right}
                className="!w-3 !h-3 !bg-surface-3 !border-2 !border-white/20 hover:!border-accent-primary hover:!bg-accent-primary/20 !-right-1.5 transition-all"
            />

            {/* Content */}
            <div className="px-3 py-2.5">
                {/* Header: type badge + status */}
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase font-bold tracking-wider opacity-70">
                        {getRoleIcon(nodeType)}
                        <span>{nodeType}</span>
                    </div>
                    <div className={`flex items-center gap-1 ${statusCfg.color}`}>
                        <StatusIcon size={12} className={isRunning ? 'animate-pulse' : ''} />
                        <span className="text-[9px] font-bold uppercase tracking-wide">
                            {statusCfg.label}
                        </span>
                    </div>
                </div>

                {/* Label */}
                <div className="text-[13px] font-semibold text-text-primary truncate leading-tight mb-1.5">
                    {label}
                </div>

                {/* Model tag */}
                <div className="flex items-center gap-1.5">
                    <span className="text-[9px] font-mono text-text-tertiary bg-white/[0.04] px-1.5 py-0.5 rounded truncate max-w-[140px]">
                        {model || 'auto'}
                    </span>
                </div>

                {/* Error preview */}
                {isError && nodeError && (
                    <div className="mt-2 px-2 py-1.5 bg-red-500/10 border border-red-500/20 rounded-lg text-[10px] text-red-300 line-clamp-2">
                        {typeof nodeError === 'string' ? nodeError : 'Error en ejecucion'}
                    </div>
                )}

                {/* Done output preview */}
                {isDone && output && (
                    <div className="mt-2 px-2 py-1.5 bg-emerald-500/5 border border-emerald-500/10 rounded-lg text-[10px] text-emerald-300/70 line-clamp-2 font-mono">
                        {typeof output === 'string' ? output.slice(0, 100) : 'Output disponible'}
                    </div>
                )}
            </div>
        </div>
    );
});

ComposerNode.displayName = 'ComposerNode';
