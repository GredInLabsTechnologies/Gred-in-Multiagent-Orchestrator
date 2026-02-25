import React, { useState } from 'react';
import { Plus, Database, ChevronRight, BarChart2 } from 'lucide-react';
import { useEvalsService } from '../../hooks/useEvalsService';
import { EvalDatasetEditor } from './EvalDatasetEditor';
import { EvalRunViewer } from './EvalRunViewer';
import { EvalDataset, EvalRunSummary } from '../../types';

export const EvalDashboard: React.FC = () => {
    const { datasets, runs, createDataset, isLoading } = useEvalsService();
    const [view, setView] = useState<'list' | 'editor' | 'run'>('list');
    const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
    const [selectedDataset, setSelectedDataset] = useState<EvalDataset | null>(null);

    const handleCreateDataset = () => {
        setSelectedDataset(null);
        setView('editor');
    };

    const handleSaveDataset = async (dataset: EvalDataset) => {
        await createDataset(dataset);
        setView('list');
    };

    const handleViewRun = (runId: number) => {
        setSelectedRunId(runId);
        setView('run');
    };

    const safeDatasets = Array.isArray(datasets) ? datasets : [];
    const safeRuns = Array.isArray(runs) ? runs : [];

    if (view === 'editor') {
        return (
            <EvalDatasetEditor
                initialData={selectedDataset || undefined}
                onSave={handleSaveDataset}
                onCancel={() => setView('list')}
            />
        );
    }

    if (view === 'run' && selectedRunId) {
        return (
            <EvalRunViewer
                runId={selectedRunId}
                onBack={() => setView('list')}
            />
        );
    }

    return (
        <div className="h-full flex flex-col bg-[#0a0a0a]">
            {/* Header */}
            <div className="p-6 border-b border-[#1c1c1e] shrink-0">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-[#f5f5f7]">Evaluaciones</h1>
                        <p className="text-[#86868b] mt-1">Test regression de workflows contra datasets golden.</p>
                    </div>
                    <button
                        onClick={handleCreateDataset}
                        className="flex items-center gap-2 px-4 py-2 bg-[#0a84ff] hover:bg-[#0071e3] text-white rounded-lg font-medium transition-colors shadow-lg shadow-[#0a84ff]/20"
                    >
                        <Plus size={16} />
                        Nuevo Dataset
                    </button>
                </div>
            </div>

            <div className="flex-1 flex overflow-hidden">
                {/* Datasets List */}
                <div className="w-1/3 border-r border-[#1c1c1e] flex flex-col">
                    <div className="p-4 border-b border-[#1c1c1e] bg-[#141414]">
                        <div className="flex items-center gap-2 text-[#f5f5f7] font-semibold">
                            <Database size={16} className="text-[#0a84ff]" />
                            Datasets
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3">
                        {isLoading && (
                            <div className="text-center text-[#86868b] py-8">Cargando...</div>
                        )}

                        {!isLoading && safeDatasets.length === 0 && (
                            <div className="text-center text-[#86868b] py-8 text-sm">Sin datasets</div>
                        )}

                        {!isLoading && safeDatasets.map((d: EvalDataset) => (
                            <button key={d.id}
                                className="w-full text-left p-4 rounded-xl bg-[#1c1c1e] border border-[#2c2c2e] hover:border-[#0a84ff]/50 transition-colors group cursor-pointer outline-none focus:ring-2 focus:ring-[#0a84ff]"
                                onClick={() => {
                                    setSelectedDataset(d);
                                    setView('editor');
                                }}
                            >
                                <div className="flex items-start justify-between">
                                    <div>
                                        <div className="font-semibold text-[#f5f5f7]">{d.name}</div>
                                        <div className="text-xs text-[#86868b] mt-1">{d.cases.length} cases • {d.workflow_id}</div>
                                    </div>
                                    <ChevronRight size={16} className="text-[#86868b] opacity-0 group-hover:opacity-100 transition-opacity" />
                                </div>
                                {d.description && <div className="text-xs text-[#86868b] mt-3 line-clamp-2">{d.description}</div>}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Runs List */}
                <div className="flex-1 flex flex-col">
                    <div className="p-4 border-b border-[#1c1c1e] bg-[#141414]">
                        <div className="flex items-center gap-2 text-[#f5f5f7] font-semibold">
                            <BarChart2 size={16} className="text-[#32d74b]" />
                            Ejecuciones Recientes
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="text-[10px] uppercase text-[#86868b] font-bold border-b border-[#2c2c2e]">
                                    <th className="pb-3 pl-4">Estado</th>
                                    <th className="pb-3">Dataset</th>
                                    <th className="pb-3">Tasa de éxito</th>
                                    <th className="pb-3">Fecha</th>
                                    <th className="pb-3 pr-4 text-right">Acción</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[#1c1c1e]">
                                {safeRuns.map((r: EvalRunSummary) => (
                                    <tr key={r.run_id} className="group hover:bg-[#141414] transition-colors">
                                        <td className="py-4 pl-4">
                                            <div className={`inline-flex items-center px-2 py-1 rounded-full text-[10px] font-bold ${r.gate_passed ? 'bg-[#32d74b]/10 text-[#32d74b]' : 'bg-[#ff453a]/10 text-[#ff453a]'
                                                }`}>
                                                {r.gate_passed ? 'PASSED' : 'FAILED'}
                                            </div>
                                        </td>
                                        <td className="py-4 text-sm text-[#f5f5f7]">Dataset #{r.dataset_id}</td>
                                        <td className="py-4">
                                            <div className="flex items-center gap-2">
                                                <div className="w-16 h-1.5 bg-[#2c2c2e] rounded-full overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full ${r.pass_rate >= 100 ? 'bg-[#32d74b]' : 'bg-[#ff9f0a]'}`}
                                                        style={{ width: `${r.pass_rate}%` }}
                                                    />
                                                </div>
                                                <span className="text-xs text-[#86868b] font-mono">{r.pass_rate.toFixed(0)}%</span>
                                            </div>
                                        </td>
                                        <td className="py-4 text-xs text-[#86868b]">{new Fecha(r.created_at).toLocaleFechaString()}</td>
                                        <td className="py-4 pr-4 text-right">
                                            <button
                                                onClick={() => handleViewRun(r.run_id)}
                                                className="text-[#0a84ff] hover:text-[#0071e3] text-xs font-medium opacity-0 group-hover:opacity-100 transition-all flex items-center justify-end gap-1 ml-auto"
                                            >
                                                Ver Reporte
                                                <ChevronRight size={12} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                                {!isLoading && safeRuns.length === 0 && (
                                    <tr>
                                        <td colSpan={5} className="py-8 text-center text-[#86868b] text-sm">Sin ejecuciones registradas</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );
};
