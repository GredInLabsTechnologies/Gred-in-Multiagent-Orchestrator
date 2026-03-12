import React from 'react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Download } from 'lucide-react';

interface ModelEntry {
    id: string;
    label: string;
    size?: string;
    [key: string]: any;
}

interface ModelGroups {
    installed: ModelEntry[];
    available: ModelEntry[];
    recommended: ModelEntry[];
}

interface OllamaLocalSectionProps {
    catalog: any;
    modelGroups: ModelGroups;
    isLoadingCatalog: boolean;
    modelId: string;
    onModelIdChange: (id: string) => void;
    onAssignOrchestrator: (modelId: string) => void;
    onAddWorker: (modelId: string) => void;
    onInstallModel: (modelId?: string) => void;
    addToast: (msg: string, type?: 'error' | 'success' | 'info') => void;
}

export const OllamaLocalSection: React.FC<OllamaLocalSectionProps> = ({
    catalog,
    modelGroups,
    isLoadingCatalog,
    modelId,
    onModelIdChange,
    onAssignOrchestrator,
    onAddWorker,
    onInstallModel,
    addToast,
}) => {
    if (!catalog) {
        return (
            <div className="p-8 text-center bg-surface-0 rounded border border-border-primary text-text-secondary">
                {isLoadingCatalog ? 'Buscando servidor Ollama local...' : 'No se pudo conectar con Ollama.'}
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between mb-2">
                <div>
                    <h4 className="text-sm font-semibold text-white">Modelos Detectados (Zero-Config)</h4>
                    <p className="text-xs text-text-secondary">No necesitas API Keys. Selecciona un modelo para asignar su rol en el enjambre.</p>
                </div>
            </div>
            {modelGroups.installed.length === 0 ? (
                <div className="p-8 text-center bg-surface-0 rounded border border-border-primary text-text-secondary">
                    Ollama está instalado, pero no tienes modelos descargados.
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {modelGroups.installed.map(m => (
                        <div key={m.id} className="p-3 bg-surface-0 border border-border-primary hover:border-surface-3 rounded-xl flex flex-col justify-between transition-colors">
                            <div>
                                <div className="font-semibold text-sm text-white truncate" title={m.label}>{m.label}</div>
                                <div className="text-[10px] text-text-secondary uppercase tracking-wider">{m.size || 'Desconocido'}</div>
                            </div>
                            <div className="flex items-center gap-2 mt-4">
                                <Button
                                    size="sm"
                                    className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] h-7 px-2"
                                    onClick={() => onAssignOrchestrator(m.id)}
                                >
                                    Asignar Orchestrator
                                </Button>
                                <Button
                                    size="sm"
                                    className="flex-1 bg-surface-3 hover:bg-surface-3 text-white text-[11px] h-7 px-2"
                                    onClick={() => onAddWorker(m.id)}
                                >
                                    Añadir Worker
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <div className="mt-6 border-t border-border-primary pt-4">
                <h4 className="text-sm font-semibold text-white mb-2">Descargar Modelos (Pull)</h4>
                <p className="text-xs text-text-secondary mb-4">Descarga nuevos modelos directamente desde el registro de Ollama.</p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {modelGroups.recommended.filter((m: any) => !m.installed).map((m: any) => (
                        <div key={m.id} className="p-3 bg-surface-2 border border-border-primary hover:border-surface-3 transition-colors rounded-xl flex items-center justify-between">
                            <div>
                                <div className="text-sm text-white font-medium">{m.label || m.id}</div>
                                <div className="text-xs text-text-secondary">{m.id}</div>
                            </div>
                            <Button
                                size="sm"
                                className="bg-surface-3 hover:bg-accent-primary hover:text-white transition-colors text-xs"
                                onClick={() => {
                                    onModelIdChange(m.id);
                                    onInstallModel(m.id);
                                }}
                            >
                                <Download className="w-3.5 h-3.5 mr-1" />
                                Descargar
                            </Button>
                        </div>
                    ))}

                    <div className="p-3 bg-surface-2 border border-border-primary rounded-xl flex flex-col justify-between">
                        <div className="text-sm text-white font-medium mb-2">Otro Modelo...</div>
                        <div className="flex items-center gap-2">
                            <Input
                                placeholder="ej: mistral:instruct"
                                className="h-8 text-xs bg-surface-0 border-border-primary text-white"
                                value={modelId}
                                onChange={(e) => onModelIdChange(e.target.value)}
                            />
                            <Button
                                size="sm"
                                title="Descargar desde Ollama"
                                className="bg-surface-3 hover:bg-accent-primary hover:text-white transition-colors text-xs shrink-0 h-8 w-8 p-0 flex items-center justify-center"
                                onClick={() => {
                                    if (modelId) onInstallModel();
                                    else addToast('Escribe el tag del modelo', 'info');
                                }}
                            >
                                <Download className="w-4 h-4" />
                            </Button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
