import React, { useCallback, useEffect, useState } from 'react';
import { API_BASE, UserEconomyConfig } from '../types';
import { ProviderSettings } from './ProviderSettings';
import { Shield, SlidersHorizontal, Coins, Info, ArrowRight } from 'lucide-react';
import { useToast } from './Toast';

interface SettingsPanelProps {
    onOpenMastery: () => void;
}

interface OpsConfig {
    default_auto_run: boolean;
    draft_cleanup_ttl_days: number;
    max_concurrent_runs: number;
    operator_can_generate: boolean;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ onOpenMastery }) => {
    const { addToast } = useToast();
    const [config, setConfig] = useState<OpsConfig | null>(null);
    const [statusInfo, setStatusInfo] = useState<{ version?: string; uptime_seconds?: number } | null>(null);
    const [economyConfig, setEconomyConfig] = useState<UserEconomyConfig | null>(null);
    const [economySaving, setEconomySaving] = useState(false);
    const [economyMessage, setEconomyMessage] = useState<string>('');

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [configRes, statusRes] = await Promise.all([
                    fetch(`${API_BASE}/ops/config`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ui/status`, { credentials: 'include' }),
                ]);

                if (configRes.ok) setConfig(await configRes.json());
                if (statusRes.ok) setStatusInfo(await statusRes.json());

                const economyRes = await fetch(`${API_BASE}/ops/mastery/config/economy`, { credentials: 'include' });
                if (economyRes.ok) setEconomyConfig(await economyRes.json());
            } catch {
                // non-blocking for settings UI
            }
        };

        fetchData();
    }, []);

    const formatUptime = (seconds?: number) => {
        if (!seconds || seconds < 0) return '—';
        const total = Math.floor(seconds);
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        return `${hours}h ${minutes}m`;
    };

    const toggleConfig = useCallback(async (key: keyof OpsConfig, value: boolean) => {
        if (!config) return;
        const updated = { ...config, [key]: value };
        setConfig(updated);
        try {
            const res = await fetch(`${API_BASE}/ops/config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(updated),
            });
            if (!res.ok) throw new Error();
            addToast(`${key} ${value ? 'activado' : 'desactivado'}`, 'success');
        } catch {
            setConfig(config);
            addToast('No se pudo guardar la configuración.', 'error');
        }
    }, [config, addToast]);

    const saveEconomy = async () => {
        if (!economyConfig) return;
        setEconomySaving(true);
        setEconomyMessage('');
        try {
            const res = await fetch(`${API_BASE}/ops/mastery/config/economy`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(economyConfig),
            });
            if (!res.ok) throw new Error('save_failed');
            setEconomyMessage('Economía guardada.');
        } catch {
            setEconomyMessage('No se pudo guardar la configuración de Economía.');
        } finally {
            setEconomySaving(false);
        }
    };

    return (
        <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-[#0a0a0a]">
            <div className="max-w-6xl mx-auto space-y-6">
                <section className="rounded-2xl border border-[#2c2c2e] bg-[#141414] p-5">
                    <div className="flex items-center gap-2 mb-4">
                        <SlidersHorizontal size={16} className="text-[#0a84ff]" />
                        <h2 className="text-sm font-black uppercase tracking-widest text-[#f5f5f7]">General</h2>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                        <SettingCell label="Tema" value="macOS Oscuro" />
                        <SettingCell label="Idioma" value="es" />
                        <ToggleCell
                            label="Auto-ejecución"
                            checked={config?.default_auto_run ?? false}
                            onChange={(v) => toggleConfig('default_auto_run', v)}
                        />
                        <SettingCell label="Concurrencia" value={String(config?.max_concurrent_runs ?? '—')} />
                        <SettingCell label="TTL borradores" value={`${config?.draft_cleanup_ttl_days ?? '—'} días`} />
                        <ToggleCell
                            label="Operador genera"
                            checked={config?.operator_can_generate ?? false}
                            onChange={(v) => toggleConfig('operator_can_generate', v)}
                        />
                    </div>
                </section>

                <section className="rounded-2xl border border-[#2c2c2e] bg-[#141414] p-5">
                    <div className="flex items-center gap-2 mb-4">
                        <Coins size={16} className="text-[#af52de]" />
                        <h2 className="text-sm font-black uppercase tracking-widest text-[#f5f5f7]">Economía</h2>
                    </div>
                    {economyConfig ? (
                        <div className="space-y-3">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                                <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3">
                                    <label htmlFor="settings-autonomy" className="text-[10px] uppercase tracking-widest text-[#86868b]">Autonomía</label>
                                    <select
                                        id="settings-autonomy"
                                        value={economyConfig.autonomy_level}
                                        onChange={(e) => setEconomyConfig({ ...economyConfig, autonomy_level: e.target.value as UserEconomyConfig['autonomy_level'] })}
                                        className="mt-1 w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded px-2 py-1 text-xs text-[#f5f5f7]"
                                    >
                                        <option value="manual">manual</option>
                                        <option value="advisory">consultivo</option>
                                        <option value="guided">guiado</option>
                                        <option value="autonomous">autónomo</option>
                                    </select>
                                </div>

                                <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3">
                                    <label htmlFor="settings-budget" className="text-[10px] uppercase tracking-widest text-[#86868b]">Presupuesto Global (USD)</label>
                                    <input
                                        id="settings-budget"
                                        type="number"
                                        value={economyConfig.global_budget_usd ?? ''}
                                        onChange={(e) => setEconomyConfig({ ...economyConfig, global_budget_usd: e.target.value ? Number(e.target.value) : null })}
                                        className="mt-1 w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded px-2 py-1 text-xs text-[#f5f5f7]"
                                    />
                                </div>

                                <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3">
                                    <label htmlFor="settings-cache-ttl" className="text-[10px] uppercase tracking-widest text-[#86868b]">TTL Caché (h)</label>
                                    <input
                                        id="settings-cache-ttl"
                                        type="number"
                                        value={economyConfig.cache_ttl_hours}
                                        onChange={(e) => setEconomyConfig({ ...economyConfig, cache_ttl_hours: Number(e.target.value) || 0 })}
                                        className="mt-1 w-full bg-[#1c1c1e] border border-[#2c2c2e] rounded px-2 py-1 text-xs text-[#f5f5f7]"
                                    />
                                </div>

                                <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3">
                                    <div className="text-[10px] uppercase tracking-widest text-[#86868b]">Indicadores</div>
                                    <div className="mt-1 space-y-1 text-xs text-[#f5f5f7]">
                                        <label className="flex items-center gap-2">
                                            <input
                                                type="checkbox"
                                                checked={economyConfig.cache_enabled}
                                                onChange={(e) => setEconomyConfig({ ...economyConfig, cache_enabled: e.target.checked })}
                                            /> caché
                                        </label>
                                        <label className="flex items-center gap-2">
                                            <input
                                                type="checkbox"
                                                checked={economyConfig.show_cost_predictions}
                                                onChange={(e) => setEconomyConfig({ ...economyConfig, show_cost_predictions: e.target.checked })}
                                            /> predicciones
                                        </label>
                                    </div>
                                </div>
                            </div>

                            <div className="flex items-center gap-3">
                                <button
                                    onClick={saveEconomy}
                                    disabled={economySaving}
                                    className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-[#af52de]/15 text-[#d4a5f2] border border-[#af52de]/30 hover:bg-[#af52de]/25 disabled:opacity-50"
                                >
                                    Guardar Economía
                                </button>
                                {economyMessage && <span className="text-xs text-[#86868b]">{economyMessage}</span>}
                                <button
                                    onClick={onOpenMastery}
                                    className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-[#1c1c1e] text-[#86868b] border border-[#2c2c2e] hover:text-[#f5f5f7]"
                                >
                                    Panel de Economía
                                    <ArrowRight size={12} />
                                </button>
                            </div>
                        </div>
                    ) : (
                        <p className="text-xs text-[#86868b]">Configuración de Economía no disponible.</p>
                    )}
                </section>

                <section className="rounded-2xl border border-[#2c2c2e] bg-[#141414] p-5">
                    <div className="flex items-center gap-2 mb-4">
                        <Shield size={16} className="text-[#ff9f0a]" />
                        <h2 className="text-sm font-black uppercase tracking-widest text-[#f5f5f7]">Seguridad</h2>
                    </div>
                    <p className="text-xs text-[#86868b]">
                        Las políticas, interruptores de circuito y dimensiones de confianza se gestionan desde la vista de Seguridad.
                    </p>
                </section>

                <section className="rounded-2xl border border-[#2c2c2e] bg-[#141414] p-5">
                    <div className="flex items-center gap-2 mb-4">
                        <Info size={16} className="text-[#32d74b]" />
                        <h2 className="text-sm font-black uppercase tracking-widest text-[#f5f5f7]">Acerca de</h2>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                        <SettingCell label="Versión" value={statusInfo?.version ?? '—'} />
                        <SettingCell label="Uptime" value={formatUptime(statusInfo?.uptime_seconds)} />
                        <SettingCell label="Endpoints" value="/ui/* + /ops/*" />
                    </div>
                </section>

                <ProviderSettings />
            </div>
        </div>
    );
};

const SettingCell: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3">
        <div className="text-[10px] uppercase tracking-widest text-[#86868b] mb-1">{label}</div>
        <div className="text-[#f5f5f7] font-medium">{value}</div>
    </div>
);

const ToggleCell: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void }> = ({ label, checked, onChange }) => (
    <div className="rounded-xl border border-[#2c2c2e] bg-[#101011] p-3 flex items-center justify-between">
        <div>
            <div className="text-[10px] uppercase tracking-widest text-[#86868b] mb-1">{label}</div>
            <div className="text-[#f5f5f7] font-medium text-xs">{checked ? 'activado' : 'desactivado'}</div>
        </div>
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${checked ? 'bg-[#0a84ff]' : 'bg-[#3a3a3c]'}`}
        >
            <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0'}`} />
        </button>
    </div>
);
