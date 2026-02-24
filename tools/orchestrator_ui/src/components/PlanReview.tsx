import React from 'react';
import { Check, Edit2, Play, AlertCircle, Clock } from 'lucide-react';
import { Plan } from '../types';

interface PlanReviewProps {
    plan: Plan;
    onApprove: () => void;
    onModify: () => void;
    loading: boolean;
}

export const PlanReview: React.FC<PlanReviewProps> = ({ plan, onApprove, onModify, loading }) => {
    return (
        <div className="flex flex-col h-full bg-[#0a0a0a]">
            <div className="p-6 space-y-6 flex-1 overflow-y-auto custom-scrollbar">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-[#32d74b]/10 flex items-center justify-center text-[#32d74b]">
                            <Check size={20} />
                        </div>
                        <div>
                            <h2 className="text-lg font-semibold text-[#f5f5f7]">{plan.title}</h2>
                            <div className="flex items-center gap-2 mt-0.5">
                                <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#1c1c1e] border border-[#2c2c2e] text-[#86868b] font-bold uppercase tracking-wider">
                                    {plan.status}
                                </span>
                                <span className="text-[10px] text-[#424245] flex items-center gap-1">
                                    <Clock size={10} /> {plan.tasks.length} sub-tareas
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="space-y-4">
                    <div className="text-[10px] uppercase tracking-widest font-bold text-[#86868b] pl-1">
                        Secuencia de Tareas
                    </div>
                    {plan.tasks.map((task, idx) => (
                        <div key={task.id} className="relative pl-8 pb-6 last:pb-0">
                            {/* Connector Line */}
                            {idx !== plan.tasks.length - 1 && (
                                <div className="absolute left-[11px] top-6 bottom-0 w-[1px] bg-gradient-to-b from-[#2c2c2e] to-transparent" />
                            )}

                            {/* Step Indicator */}
                            <div className={`
                                absolute left-0 top-0 w-[23px] h-[23px] rounded-full border-2 flex items-center justify-center text-[10px] font-bold
                                ${task.status === 'done' ? 'bg-[#32d74b] border-[#32d74b] text-[#000]' : 'bg-[#0a0a0a] border-[#2c2c2e] text-[#86868b]'}
                            `}>
                                {idx + 1}
                            </div>

                            <div className="p-4 rounded-xl bg-[#141414] border border-[#1c1c1e] hover:border-[#2c2c2e] transition-all">
                                <div className="flex items-center justify-between mb-1">
                                    <h4 className="text-xs font-semibold text-[#f5f5f7]">{task.title}</h4>
                                    <div className="flex items-center gap-1">
                                        {plan.assignments.find(a => a.taskIds.includes(task.id)) && (
                                            <span className="text-[8px] bg-[#0a84ff]/10 text-[#0a84ff] px-1.5 py-0.5 rounded-md font-bold uppercase">
                                                {plan.assignments.find(a => a.taskIds.includes(task.id))?.agentId}
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <p className="text-[11px] text-[#86868b] leading-relaxed">{task.description}</p>
                            </div>
                        </div>
                    ))}
                </div>

                <div className="p-4 rounded-xl bg-[#ff9f0a]/5 border border-[#ff9f0a]/20 flex gap-3">
                    <AlertCircle size={14} className="text-[#ff9f0a] shrink-0 mt-0.5" />
                    <div>
                        <h4 className="text-[10px] font-bold text-[#ff9f0a] uppercase tracking-wider mb-1">Aviso de Seguridad</h4>
                        <p className="text-[10px] text-[#ff9f0a]/80 leading-relaxed">
                            Este plan se ejecutará con confianza <b>Supervisada</b>. GIMO esperará tu confirmación antes de finalizar cualquier cambio en los archivos.
                        </p>
                    </div>
                </div>
            </div>

            <div className="p-6 border-t border-[#1c1c1e] bg-[#000000]/50 flex gap-3">
                <button
                    onClick={onModify}
                    className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-[10px] uppercase tracking-widest text-[#86868b] border border-[#2c2c2e] hover:bg-[#1c1c1e] transition-all"
                >
                    <Edit2 size={12} />
                    Modificar Plan
                </button>
                <button
                    onClick={onApprove}
                    disabled={loading}
                    className="flex-[2] flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-xs uppercase tracking-widest bg-[#32d74b] text-black hover:bg-[#28b33f] shadow-lg shadow-[#32d74b]/20 active:scale-[0.98] transition-all"
                >
                    {loading ? (
                        <div className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                    ) : (
                        <>
                            <Play size={14} fill="currentColor" />
                            Aprobar y Lanzar
                        </>
                    )}
                </button>
            </div>
        </div>
    );
};
