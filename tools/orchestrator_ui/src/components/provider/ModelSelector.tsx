import React from 'react';
import { Input } from '../ui/input';
import { ChevronDown } from 'lucide-react';

interface ModelEntry {
    id: string;
    label: string;
    [key: string]: any;
}

interface ModelGroups {
    installed: ModelEntry[];
    available: ModelEntry[];
    recommended: ModelEntry[];
}

interface ModelSelectorProps {
    modelId: string;
    modelGroups: ModelGroups;
    isLoading: boolean;
    supportsInstall: boolean;
    modelSearch: string;
    modelDropdownOpen: boolean;
    onSelect: (id: string) => void;
    onSearchChange: (q: string) => void;
    onToggleDropdown: () => void;
    renderModelMeta: (m: any) => string;
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({
    modelId,
    modelGroups,
    isLoading,
    supportsInstall,
    modelSearch,
    modelDropdownOpen,
    onSelect,
    onSearchChange,
    onToggleDropdown,
    renderModelMeta,
}) => {
    const filteredGroups = React.useMemo(() => {
        const q = modelSearch.trim().toLowerCase();
        if (!q) return modelGroups;
        const filterModels = (items: ModelEntry[]) => items.filter((m) => {
            const id = String(m?.id || '').toLowerCase();
            const label = String(m?.label || '').toLowerCase();
            return id.includes(q) || label.includes(q);
        });
        return {
            installed: filterModels(modelGroups.installed),
            available: filterModels(modelGroups.available),
            recommended: filterModels(modelGroups.recommended),
        };
    }, [modelGroups, modelSearch]);

    return (
        <div className="relative">
            <button
                type="button"
                onClick={onToggleDropdown}
                className="w-full bg-surface-0 border border-border-primary rounded-lg p-2.5 text-sm text-text-primary text-left focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all shadow-sm flex items-center justify-between"
            >
                <span>{modelId || (isLoading ? 'Cargando catálogo...' : 'Selecciona modelo')}</span>
                <ChevronDown className={`w-4 h-4 text-text-secondary transition-transform ${modelDropdownOpen ? 'rotate-180' : ''}`} />
            </button>
            {modelDropdownOpen && (
                <div className="absolute z-30 mt-2 w-full bg-surface-1 border border-border-primary rounded-lg shadow-xl p-2">
                    <Input
                        autoFocus
                        value={modelSearch}
                        onChange={(e) => onSearchChange(e.target.value)}
                        placeholder="Buscar modelo dentro del dropdown..."
                        className="mb-2 bg-surface-0 border-border-primary text-text-primary"
                    />
                    <div className="max-h-72 overflow-auto space-y-2">
                        {filteredGroups.installed.length > 0 && (
                            <div>
                                <div className="px-2 py-1 text-[11px] uppercase text-text-secondary">{supportsInstall ? 'Instalados' : 'En uso'}</div>
                                {filteredGroups.installed.map((m) => (
                                    <button
                                        key={`i-${m.id}`}
                                        type="button"
                                        onClick={() => onSelect(m.id)}
                                        className={`w-full text-left px-2 py-1.5 text-sm rounded ${modelId === m.id ? 'bg-indigo-500/20 text-indigo-200' : 'hover:bg-surface-2 text-text-primary'}`}
                                    >
                                        <div className="font-medium">{m.label}</div>
                                        <div className="text-[10px] text-text-secondary mt-0.5">{renderModelMeta(m)}</div>
                                    </button>
                                ))}
                            </div>
                        )}
                        {filteredGroups.available.length > 0 && (
                            <div>
                                <div className="px-2 py-1 text-[11px] uppercase text-text-secondary">{supportsInstall ? 'Disponibles para descargar' : 'Más modelos'}</div>
                                {filteredGroups.available.map((m) => (
                                    <button
                                        key={`a-${m.id}`}
                                        type="button"
                                        onClick={() => onSelect(m.id)}
                                        className={`w-full text-left px-2 py-1.5 text-sm rounded ${modelId === m.id ? 'bg-indigo-500/20 text-indigo-200' : 'hover:bg-surface-2 text-text-primary'}`}
                                    >
                                        <div className="font-medium">{m.label}</div>
                                        <div className="text-[10px] text-text-secondary mt-0.5">{renderModelMeta(m)}</div>
                                    </button>
                                ))}
                            </div>
                        )}
                        {filteredGroups.recommended.length > 0 && (
                            <div>
                                <div className="px-2 py-1 text-[11px] uppercase text-text-secondary">{supportsInstall ? 'Recomendados' : 'Sugeridos'}</div>
                                {filteredGroups.recommended.map((m) => (
                                    <button
                                        key={`r-${m.id}`}
                                        type="button"
                                        onClick={() => onSelect(m.id)}
                                        className={`w-full text-left px-2 py-1.5 text-sm rounded ${modelId === m.id ? 'bg-indigo-500/20 text-indigo-200' : 'hover:bg-surface-2 text-text-primary'}`}
                                    >
                                        <div className="font-medium">{m.label}</div>
                                        <div className="text-[10px] text-text-secondary mt-0.5">{renderModelMeta(m)}</div>
                                    </button>
                                ))}
                            </div>
                        )}
                        {filteredGroups.installed.length === 0 && filteredGroups.available.length === 0 && filteredGroups.recommended.length === 0 && (
                            <div className="px-2 py-2 text-xs text-text-secondary">Sin resultados</div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};
