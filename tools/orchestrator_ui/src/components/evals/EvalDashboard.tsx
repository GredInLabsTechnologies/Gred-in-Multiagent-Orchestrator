import React, { useState } from 'react';
import { Plus, Database, ChevronRight, BarChart2 } from 'lucide-react';
import { useEvalsService } from '../../hooks/useEvalsService';
import { EvalDatasetEditor } from './EvalDatasetEditor';
import { EvalRunViewer } from './EvalRunViewer';
import { EvalDataset, EvalRunSummary } from '../../types';

export const EvalDashboard: React.FC = () => {
    const { datasets, runs, createDataset, isLoading, error } = useEvalsService();
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
        <div className="h-full flex flex-col bg-surface-0">
            {/* Header */}
            <div className="p-6 border-b border-surface-2 shrink-0">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-text-primary">Evaluations</h1>
                        <p className="text-text-secondary mt-1">Validate flows with test cases before deploying changes.</p>
                    </div>
                    <button
                        onClick={handleCreateDataset}
                        className="flex items-center gap-2 px-4 py-2 bg-accent-primary hover:bg-accent-primary/80 text-white rounded-lg font-medium transition-colors shadow-lg shadow-accent-primary/20"
                    >
                        <Plus size={16} />
                        Nuevo Dataset
                    </button>
                </div>
            </div>

            <div className="flex-1 flex overflow-hidden">
                {/* Datasets List */}
                <div className="w-1/3 border-r border-surface-2 flex flex-col">
                    <div className="p-4 border-b border-surface-2 bg-surface-1">
                        <div className="flex items-center gap-2 text-text-primary font-semibold">
                            <Database size={16} className="text-accent-primary" />
                            Datasets
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3">
                        {error && (
                            <div className="text-xs rounded-lg border border-accent-alert/30 bg-accent-alert/10 text-accent-alert p-3">
                                {error}
                            </div>
                        )}
                        {isLoading && (
                            <div className="text-center text-text-secondary py-8">Cargando...</div>
                        )}

                        {!isLoading && safeDatasets.length === 0 && (
                            <div className="text-center text-text-secondary py-8 text-sm">No datasets</div>
                        )}

                        {!isLoading && safeDatasets.map((d: EvalDataset) => (
                            <button key={d.id}
                                className="w-full text-left p-4 rounded-xl bg-surface-2 border border-border-primary hover:border-accent-primary/50 transition-colors group cursor-pointer outline-none focus:ring-2 focus:ring-accent-primary"
                                onClick={() => {
                                    setSelectedDataset(d);
                                    setView('editor');
                                }}
                            >
                                <div className="flex items-start justify-between">
                                    <div>
                                        <div className="font-semibold text-text-primary">{d.name}</div>
                                        <div className="text-xs text-text-secondary mt-1">{d.cases.length} cases • {d.workflow_id}</div>
                                    </div>
                                    <ChevronRight size={16} className="text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity" />
                                </div>
                                {d.description && <div className="text-xs text-text-secondary mt-3 line-clamp-2">{d.description}</div>}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Runs List */}
                <div className="flex-1 flex flex-col">
                    <div className="p-4 border-b border-surface-2 bg-surface-1">
                        <div className="flex items-center gap-2 text-text-primary font-semibold">
                            <BarChart2 size={16} className="text-accent-trust" />
                            Ejecuciones Recientes
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="text-[10px] uppercase text-text-secondary font-bold border-b border-border-primary">
                                    <th className="pb-3 pl-4">Estado</th>
                                    <th className="pb-3">Dataset</th>
                                    <th className="pb-3">Success rate</th>
                                    <th className="pb-3">Fecha</th>
                                    <th className="pb-3 pr-4 text-right">Acción</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-2">
                                {safeRuns.map((r: EvalRunSummary) => (
                                    <tr key={r.run_id} className="group hover:bg-surface-1 transition-colors">
                                        <td className="py-4 pl-4">
                                            <div className={`inline-flex items-center px-2 py-1 rounded-full text-[10px] font-bold ${r.gate_passed ? 'bg-accent-trust/10 text-accent-trust' : 'bg-accent-alert/10 text-accent-alert'
                                                }`}>
                                                {r.gate_passed ? 'PASSED' : 'FAILED'}
                                            </div>
                                        </td>
                                        <td className="py-4 text-sm text-text-primary">Dataset #{r.dataset_id}</td>
                                        <td className="py-4">
                                            <div className="flex items-center gap-2">
                                                <div className="w-16 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full ${r.pass_rate >= 100 ? 'bg-accent-trust' : 'bg-accent-warning'}`}
                                                        style={{ width: `${r.pass_rate}%` }}
                                                    />
                                                </div>
                                                <span className="text-xs text-text-secondary font-mono">{r.pass_rate.toFixed(0)}%</span>
                                            </div>
                                        </td>
                                        <td className="py-4 text-xs text-text-secondary">{new Date(r.created_at).toLocaleDateString()}</td>
                                        <td className="py-4 pr-4 text-right">
                                            <button
                                                onClick={() => handleViewRun(r.run_id)}
                                                className="text-accent-primary hover:text-accent-primary text-xs font-medium opacity-0 group-hover:opacity-100 transition-all flex items-center justify-end gap-1 ml-auto"
                                            >
                                                Ver Informe
                                                <ChevronRight size={12} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                                {!isLoading && safeRuns.length === 0 && (
                                    <tr>
                                        <td colSpan={5} className="py-8 text-center text-text-secondary text-sm">No recorded runs</td>
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
