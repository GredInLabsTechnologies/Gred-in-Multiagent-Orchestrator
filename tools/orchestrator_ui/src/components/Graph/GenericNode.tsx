import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import type { Node } from 'reactflow';
import { CheckCircle2, Clock, FileCode, AlertCircle, RefreshCw } from 'lucide-react';
import clsx from 'clsx';

export type GenericNodeData = {
    label: string;
    status?: 'pending' | 'running' | 'done' | 'error' | 'cancelled';
    type?: string;
    description?: string;
    meta?: Record<string, any>;
    [key: string]: unknown; // Index signature for Record<string, unknown> constraint
};

export type GenericNodeType = Node<GenericNodeData, string>;

const statusColors: Record<string, string> = {
    pending: 'border-zinc-700 text-zinc-500 bg-zinc-900/50',
    running: 'border-amber-500/50 text-amber-400 bg-amber-500/10 shadow-[0_0_30px_-5px_rgba(245,158,11,0.3)]',
    done: 'border-emerald-500/50 text-emerald-400 bg-emerald-500/10',
    error: 'border-red-500/50 text-red-400 bg-red-500/10',
    cancelled: 'border-zinc-700 text-zinc-600 bg-zinc-900/30 line-through opacity-60',
};

const StatusIcon = ({ status }: { status?: string }) => {
    switch (status) {
        case 'running': return <RefreshCw className="w-3 h-3 animate-spin" />;
        case 'done': return <CheckCircle2 className="w-3 h-3" />;
        case 'error': return <AlertCircle className="w-3 h-3" />;
        case 'pending': return <Clock className="w-3 h-3" />;
        default: return <FileCode className="w-3 h-3" />;
    }
};

export const GenericNode = memo(({ data, selected }: NodeProps<GenericNodeData>) => {
    const status = (data.status as string) || 'pending';
    const style = statusColors[status] || statusColors.pending;

    return (
        <div
            className={clsx(
                "relative min-w-[200px] rounded-xl border backdrop-blur-md transition-all duration-300",
                "flex flex-col overflow-hidden group",
                style,
                selected && "ring-2 ring-blue-500 ring-offset-2 ring-offset-black scale-105 z-10"
            )}
        >
            {/* Input Handle */}
            <Handle
                type="target"
                position={Position.Left}
                className="!w-2 !h-8 !bg-zinc-800 !border-none !rounded-r-full !-left-2 transition-colors group-hover:!bg-blue-500"
            />

            {/* Header / Main Content */}
            <div className="p-3">
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                        <div className={clsx("p-1.5 rounded-lg bg-black/20", status === 'running' && "animate-pulse")}>
                            <StatusIcon status={status} />
                        </div>
                        <span className="text-[10px] font-mono opacity-60 uppercase tracking-wider">
                            {(data.type as string) || 'TASK'}
                        </span>
                    </div>
                    {data.meta && (data.meta as any).duration_ms && (
                        <span className="text-[9px] font-mono opacity-50">
                            {((data.meta as any).duration_ms / 1000).toFixed(2)}s
                        </span>
                    )}
                </div>

                <div className="font-bold text-xs/tight mb-1">
                    {data.label as string}
                </div>

                {data.description && (
                    <div className="text-[10px] opacity-60 line-clamp-2 leading-relaxed">
                        {data.description as string}
                    </div>
                )}
            </div>

            {/* Progress Bar (if running) */}
            {status === 'running' && (
                <div className="h-0.5 w-full bg-amber-900/30 overflow-hidden">
                    <div className="h-full w-1/3 bg-amber-500 animate-pulse" />
                </div>
            )}

            {/* Output Handle */}
            <Handle
                type="source"
                position={Position.Right}
                className="!w-2 !h-8 !bg-zinc-800 !border-none !rounded-l-full !-right-2 transition-colors group-hover:!bg-blue-500"
            />
        </div>
    );
});
