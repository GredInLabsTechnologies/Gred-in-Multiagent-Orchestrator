import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE, OpsApproved, OpsDraft, OpsRun, Plan, PlanCreateRequest } from '../types';
import { PlanBuilder } from './PlanBuilder';
import { PlanReview } from './PlanReview';
import { Clock3, CheckCircle2, FileText, PlayCircle } from 'lucide-react';
import { useToast } from './Toast';

interface PlansPanelProps {
    currentPlan: Plan | null;
    loading: boolean;
    onCreatePlan: (req: PlanCreateRequest) => Promise<void>;
    onApprovePlan: () => Promise<void>;
    onDiscardPlan?: () => void;
}

type TimelineItem = {
    id: string;
    type: 'draft' | 'approved' | 'run';
    status: string;
    title: string;
    createdAt: string;
    subtitle?: string;
};

export const PlansPanel: React.FC<PlansPanelProps> = ({
    currentPlan,
    loading,
    onCreatePlan,
    onApprovePlan,
    onDiscardPlan,
}) => {
    const { addToast } = useToast();
    const [drafts, setDrafts] = useState<OpsDraft[]>([]);
    const [approved, setApproved] = useState<OpsApproved[]>([]);
    const [runs, setRuns] = useState<OpsRun[]>([]);

    useEffect(() => {
        let cancelled = false;

        const fetchHistory = async () => {
            try {
                const [dRes, aRes, rRes] = await Promise.all([
                    fetch(`${API_BASE}/ops/drafts`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ops/approved`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ops/runs`, { credentials: 'include' }),
                ]);

                if (!cancelled) {
                    if (dRes.ok) setDrafts(await dRes.json());
                    if (aRes.ok) setApproved(await aRes.json());
                    if (rRes.ok) setRuns(await rRes.json());
                }
            } catch {
                if (!cancelled) addToast('No se pudo cargar el historial de planes.', 'error');
            }
        };

        fetchHistory();
        const interval = globalThis.setInterval(fetchHistory, 5000);
        return () => {
            cancelled = true;
            globalThis.clearInterval(interval);
        };
    }, [addToast]);

    const timeline = useMemo<TimelineItem[]>(() => {
        const draftItems: TimelineItem[] = drafts.map((d) => ({
            id: d.id,
            type: 'draft',
            status: d.status,
            title: d.prompt,
            createdAt: d.created_at,
        }));

        const approvedItems: TimelineItem[] = approved.map((a) => ({
            id: a.id,
            type: 'approved',
            status: 'approved',
            title: a.prompt,
            createdAt: a.approved_at,
            subtitle: `Draft: ${a.draft_id}`,
        }));

        const runItems: TimelineItem[] = runs.map((r) => ({
            id: r.id,
            type: 'run',
            status: r.status,
            title: `Run ${r.id}`,
            // created_at is nullable in the backend schema (see OpsRun). Fall back to epoch
            // so the sort below is stable; runs without created_at appear oldest.
            createdAt: r.created_at ?? new Date(0).toISOString(),
            subtitle: `Approved: ${r.approved_id}`,
        }));

        return [...draftItems, ...approvedItems, ...runItems]
            .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    }, [approved, drafts, runs]);

    return (
        <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-surface-0">
            <div className="max-w-7xl mx-auto grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-6">
                <section className="min-h-[560px] bg-[#101011] border border-border-primary rounded-2xl overflow-hidden">
                    {currentPlan ? (
                        <PlanReview
                            plan={currentPlan}
                            onApprove={onApprovePlan}
                            onModify={() => onDiscardPlan?.()}
                            loading={loading}
                        />
                    ) : (
                        <PlanBuilder onCreate={onCreatePlan} loading={loading} />
                    )}
                </section>

                <aside className="bg-[#101011] border border-border-primary rounded-2xl p-5 flex flex-col min-h-[560px]">
                    <div className="mb-4">
                        <h2 className="text-sm uppercase tracking-widest font-black text-text-primary">Historial de Planes</h2>
                        <p className="text-xs text-text-secondary mt-1">Borradores, aprobaciones y ejecuciones en una sola línea de tiempo.</p>
                    </div>

                    <div className="space-y-3 overflow-y-auto custom-scrollbar pr-1">
                        {timeline.length === 0 && (
                            <div className="h-40 flex items-center justify-center text-xs text-text-secondary border border-dashed border-border-primary rounded-xl">
                                Aún no hay historial.
                            </div>
                        )}

                        {timeline.map((item) => {
                            const statusMap: Record<string, string> = {
                                'draft': 'borrador',
                                'approved': 'aprobado',
                                'running': 'ejecutando',
                                'done': 'finalizado',
                                'failed': 'fallido',
                                'doubt': 'con dudas'
                            };
                            const displayStatus = statusMap[item.status.toLowerCase()] || item.status;

                            return (
                                <div key={`${item.type}-${item.id}`} className="rounded-xl border border-border-primary bg-surface-1 p-3">
                                    <div className="flex items-start gap-2">
                                        <div className="mt-0.5 text-text-secondary">
                                            {item.type === 'draft' && <FileText size={14} />}
                                            {item.type === 'approved' && <CheckCircle2 size={14} />}
                                            {item.type === 'run' && <PlayCircle size={14} />}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center justify-between gap-2">
                                                <span className="text-xs text-text-primary font-medium truncate">{item.title}</span>
                                                <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-surface-2 text-text-secondary border border-border-primary">
                                                    {displayStatus}
                                                </span>
                                            </div>
                                            {item.subtitle && (
                                                <p className="text-[10px] text-text-secondary mt-0.5">
                                                    <span className="opacity-50">
                                                        {item.type === 'approved' ? 'Borrador: ' : ''}
                                                        {item.type === 'run' ? 'Aprobado: ' : ''}
                                                    </span>
                                                    {item.subtitle.replace('Draft: ', '').replace('Approved: ', '')}
                                                </p>
                                            )}
                                            <div className="mt-1.5 text-[10px] text-text-secondary flex items-center gap-1">
                                                <Clock3 size={10} />
                                                {new Date(item.createdAt).toLocaleString()}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </aside>
            </div>
        </div>
    );
};
