import React, { useEffect, useState } from 'react';
import { Trace, Span } from '../../types';
import { useObservabilityService } from '../../hooks/useObservabilityService';
import { ChevronDown, Clock, AlertCircle } from 'lucide-react';

interface TraceViewerProps {
    onClose?: () => void;
}

export const TraceViewer: React.FC<TraceViewerProps> = () => {
    const { getTraces, getTraceDetail, loading } = useObservabilityService();
    const [traces, setTraces] = useState<Trace[]>([]);
    const [selectedTraceData, setSelectedTraceData] = useState<Trace | null>(null);

    useEffect(() => {
        loadTraces();
    }, []);

    const loadTraces = async () => {
        const data = await getTraces();
        setTraces(data);
    };

    const handleSelectTrace = async (traceId: string) => {
        const detail = await getTraceDetail(traceId);
        setSelectedTraceData(detail);
    };

    const safeTraces = Array.isArray(traces) ? traces : [];

    return (
        <div className="flex h-full bg-surface-0 text-text-primary overflow-hidden rounded-xl border border-border-primary">
            {/* Trace List - Left Sidebar */}
            <div className="w-1/3 border-r border-border-primary flex flex-col">
                <div className="p-3 border-b border-border-primary bg-surface-1">
                    <h3 className="text-xs font-bold uppercase tracking-widest text-text-secondary">Actividad Reciente</h3>
                </div>
                <div className="flex-1 overflow-y-auto custom-scrollbar">
                    {loading && safeTraces.length === 0 ? (
                        <div className="p-4 text-center text-text-secondary text-xs">Cargando trazas...</div>
                    ) : (
                        safeTraces.map((trace) => (
                            <div
                                key={trace.trace_id}
                                onClick={() => handleSelectTrace(trace.trace_id)}
                                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleSelectTrace(trace.trace_id); }}
                                role="button"
                                tabIndex={0}
                                className={`p-3 border-b border-surface-2 cursor-pointer hover:bg-surface-2 transition-colors ${selectedTraceData?.trace_id === trace.trace_id ? 'bg-surface-2 border-l-2 border-l-accent-primary' : ''}`}
                            >
                                <div className="flex justify-between items-start mb-1">
                                    <span className={`text-xs font-mono font-medium truncate ${trace.status === 'error' ? 'text-red-500' : 'text-text-primary'}`}>
                                        {trace.root_span?.name || 'Operación desconocida'}
                                    </span>
                                    <span className="text-[10px] text-text-secondary font-mono">
                                        {trace.duration_ms ? `${trace.duration_ms}ms` : 'running'}
                                    </span>
                                </div>
                                <div className="flex justify-between items-center text-[10px] text-text-secondary">
                                    <span className="truncate max-w-[120px]">{trace.trace_id.substring(0, 8)}...</span>
                                    <span>{new Date(trace.start_time).toLocaleTimeString()}</span>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Trace Details - Main Area */}
            <div className="flex-1 flex flex-col bg-surface-0">
                {selectedTraceData ? (
                    <>
                        <div className="p-4 border-b border-border-primary bg-surface-1 flex justify-between items-center">
                            <div>
                                <h2 className="text-sm font-bold text-text-primary mb-1">
                                    {selectedTraceData.root_span?.name || 'Traza desconocida'}
                                </h2>
                                <div className="flex items-center gap-3 text-xs text-text-secondary">
                                    <span className="font-mono text-[10px] bg-surface-2 px-1.5 py-0.5 rounded">
                                        {selectedTraceData.trace_id}
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <Clock size={12} />
                                        {new Date(selectedTraceData.start_time).toLocaleString()}
                                    </span>
                                </div>
                            </div>
                            <div className={`px-2 py-1 rounded text-xs font-bold uppercase tracking-wider ${selectedTraceData.status === 'error' ? 'bg-red-500/10 text-red-500' : 'bg-green-500/10 text-green-500'}`}>
                                {selectedTraceData.status}
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                            <SpanTree spans={Array.isArray(selectedTraceData.spans) ? selectedTraceData.spans : []} rootSpanId={selectedTraceData.root_span?.span_id || ''} />
                        </div>
                    </>
                ) : (
                    <div className="flex-1 flex items-center justify-center text-text-secondary flex-col gap-2">
                        <ActivityIcon />
                        <span className="text-xs">Select a trace to view details</span>
                    </div>
                )}
            </div>
        </div>
    );
};

// --- Helper Components ---

const ActivityIcon = () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-20">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
);

const SpanTree: React.FC<{ spans: Span[]; rootSpanId: string }> = ({ spans, rootSpanId }) => {
    // Build tree structure
    const spanMap = new Map<string, Span>();
    const childrenMap = new Map<string, Span[]>();

    spans.forEach(s => {
        spanMap.set(s.span_id, s);
        const parentId = s.parent_id || 'root';
        if (!childrenMap.has(parentId)) {
            childrenMap.set(parentId, []);
        }
        childrenMap.get(parentId)?.push(s);
    });

    // Root span might not have parent_id null depending on how it's stored, 
    // but typically the trace root has no parent. 
    // If the passed rootSpanId exists in map, start there.
    const root = spanMap.get(rootSpanId);

    if (!root) return <div className="text-red-500">Root span not found</div>;

    const renderNode = (span: Span, depth: number) => {
        const children = childrenMap.get(span.span_id) || [];
        const duration = span.end_time
            ? new Date(span.end_time).getTime() - new Date(span.start_time).getTime()
            : null;

        return (
            <div key={span.span_id} className="mb-1">
                <div
                    className="flex items-center gap-2 p-2 rounded hover:bg-surface-2 group"
                    style={{ marginLeft: `${depth * 16}px` }}
                >
                    <div className="flex-shrink-0 text-text-secondary">
                        {children.length > 0 ? <ChevronDown size={14} /> : <div className="w-[14px]" />}
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <span className={`text-xs font-mono truncate ${span.status === 'error' ? 'text-red-400' : 'text-text-primary'}`}>
                                {span.name}
                            </span>
                            {span.status === 'error' && <AlertCircle size={12} className="text-red-500" />}
                        </div>
                        {Object.keys(span.attributes).length > 0 && (
                            <div className="text-[10px] text-text-tertiary truncate mt-0.5">
                                {JSON.stringify(span.attributes)}
                            </div>
                        )}
                    </div>
                    {duration !== null && (
                        <div className="text-[10px] text-text-secondary font-mono tabular-nums">
                            {duration}ms
                        </div>
                    )}
                </div>
                {children.map(child => renderNode(child, depth + 1))}
            </div>
        );
    };

    return <div className="py-2">{renderNode(root, 0)}</div>;
};
