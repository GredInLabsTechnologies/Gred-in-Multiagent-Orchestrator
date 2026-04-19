import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_BASE, UserEconomyConfig } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { fetchOperatorStatus } from '../lib/operatorStatus';
import { Shield, SlidersHorizontal, Coins, Info, ArrowRight, Server, Wrench, Globe } from 'lucide-react';
import { useToast } from './Toast';

type SettingsSection = 'providers' | 'general' | 'economy' | 'security' | 'maintenance' | 'about' | 'language';

interface SettingsPanelProps {
    onOpenMastery: () => void;
}

interface OpsConfig {
    default_auto_run: boolean;
    draft_cleanup_ttl_days: number;
    max_concurrent_runs: number;
    operator_can_generate: boolean;
}

const NAV_ICONS: Record<SettingsSection, React.ReactNode> = {
    providers: <Server size={14} />,
    general: <SlidersHorizontal size={14} />,
    economy: <Coins size={14} />,
    security: <Shield size={14} />,
    maintenance: <Wrench size={14} />,
    about: <Info size={14} />,
    language: <Globe size={14} />,
};

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ onOpenMastery }) => {
    const { t, i18n } = useTranslation();
    const { addToast } = useToast();

    const NAV_ITEMS: { key: SettingsSection; label: string; icon: React.ReactNode }[] = [
        { key: 'providers', label: t('settings.providers'), icon: NAV_ICONS.providers },
        { key: 'general', label: t('settings.general'), icon: NAV_ICONS.general },
        { key: 'economy', label: t('inspect.cost'), icon: NAV_ICONS.economy },
        { key: 'security', label: t('settings.trust'), icon: NAV_ICONS.security },
        { key: 'maintenance', label: t('common.settings'), icon: NAV_ICONS.maintenance },
        { key: 'language', label: t('settings.language'), icon: NAV_ICONS.language },
        { key: 'about', label: 'About', icon: NAV_ICONS.about },
    ];
    const [config, setConfig] = useState<OpsConfig | null>(null);
    const [statusInfo, setStatusInfo] = useState<{ version?: string; uptime_seconds?: number } | null>(null);
    const [economyConfig, setEconomyConfig] = useState<UserEconomyConfig | null>(null);
    const [economySaving, setEconomySaving] = useState(false);
    const [economyMessage, setEconomyMessage] = useState<string>('');
    const [activeSection, setActiveSection] = useState<SettingsSection>('general');
    const [hwMetrics, setHwMetrics] = useState<any>(null);
    const [realtimeMetrics, setRealtimeMetrics] = useState<any>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [configRes, statusInfo] = await Promise.all([
                    fetchWithRetry(`${API_BASE}/ops/config`, { credentials: 'include' }),
                    fetchOperatorStatus().catch(() => null),
                ]);

                if (configRes.ok) setConfig(await configRes.json());
                if (statusInfo) setStatusInfo(statusInfo);

                const economyRes = await fetchWithRetry(`${API_BASE}/ops/mastery/config/economy`, { credentials: 'include' });
                if (economyRes.ok) setEconomyConfig(await economyRes.json());

                const [hwRes, rtRes] = await Promise.all([
                    fetchWithRetry(`${API_BASE}/ops/mastery/hardware`, { credentials: 'include' }).catch(() => null),
                    fetchWithRetry(`${API_BASE}/ops/realtime/metrics`, { credentials: 'include' }).catch(() => null),
                ]);
                if (hwRes?.ok) setHwMetrics(await hwRes.json());
                if (rtRes?.ok) setRealtimeMetrics(await rtRes.json());
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
        const previousConfig = { ...config };
        const updated = { ...config, [key]: value };
        setConfig(updated);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(updated),
            });
            if (!res.ok) throw new Error('Failed to update config');
            addToast(`${key} ${value ? 'activado' : 'desactivado'}`, 'success');
        } catch {
            setConfig(previousConfig);
            addToast('No se pudo guardar la configuración.', 'error');
        }
    }, [config, addToast]);

    const saveEconomy = async () => {
        if (!economyConfig) return;
        setEconomySaving(true);
        setEconomyMessage('');
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/config/economy`, {
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
        <div className="h-full flex bg-surface-0">
            {/* Lateral nav */}
            <nav className="w-44 shrink-0 border-r border-border-primary bg-surface-1/50 p-3 space-y-0.5" role="navigation" aria-label="Settings navigation">
                {NAV_ITEMS.map((item) => (
                    <button
                        key={item.key}
                        onClick={() => setActiveSection(item.key)}
                        className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-colors ${activeSection === item.key
                                ? 'bg-accent-primary/10 text-accent-primary'
                                : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.03]'
                            }`}
                    >
                        {item.icon}
                        {item.label}
                    </button>
                ))}
            </nav>

            {/* Content area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
                <div className="max-w-4xl mx-auto space-y-6">

                    {activeSection === 'providers' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Server size={16} className="text-blue-400" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">Proveedores</h2>
                            </div>
                            <p className="text-xs text-text-secondary mb-3">
                                Configura tus proveedores de LLM desde la vista de Proveedores en el Sidebar.
                            </p>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                                <SettingCell label="Provider activo" value={statusInfo?.version ? 'Configurado' : 'No disponible'} />
                                <SettingCell label="Modelos disponibles" value="Ver catalogo" />
                            </div>
                        </section>
                    )}

                    {activeSection === 'general' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <SlidersHorizontal size={16} className="text-accent-primary" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">General</h2>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
                                <SettingCell label="Tema" value="macOS Oscuro" />
                                <SettingCell label="Idioma" value="es" />
                                <ToggleCell
                                    label="Auto-ejecucion"
                                    checked={config?.default_auto_run ?? false}
                                    onChange={(v) => toggleConfig('default_auto_run', v)}
                                />
                                <SettingCell label="Concurrencia" value={String(config?.max_concurrent_runs ?? '—')} />
                                <SettingCell label="TTL borradores" value={`${config?.draft_cleanup_ttl_days ?? '—'} dias`} />
                                <ToggleCell
                                    label="Operador genera"
                                    checked={config?.operator_can_generate ?? false}
                                    onChange={(v) => toggleConfig('operator_can_generate', v)}
                                />
                            </div>
                        </section>
                    )}

                    {activeSection === 'economy' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Coins size={16} className="text-accent-purple" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">Economia</h2>
                            </div>
                            {economyConfig ? (
                                <div className="space-y-3">
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                                        <div className="rounded-xl border border-border-primary bg-surface-1 p-3">
                                            <label htmlFor="settings-autonomy" className="text-[10px] uppercase tracking-widest text-text-secondary">Autonomia</label>
                                            <select
                                                id="settings-autonomy"
                                                value={economyConfig.autonomy_level}
                                                onChange={(e) => setEconomyConfig({ ...economyConfig, autonomy_level: e.target.value as UserEconomyConfig['autonomy_level'] })}
                                                className="mt-1 w-full bg-surface-3 border border-border-primary rounded px-2 py-1 text-xs text-text-primary"
                                            >
                                                <option value="manual">manual</option>
                                                <option value="advisory">consultivo</option>
                                                <option value="guided">guiado</option>
                                                <option value="autonomous">autonomo</option>
                                            </select>
                                        </div>
                                        <div className="rounded-xl border border-border-primary bg-surface-1 p-3">
                                            <label htmlFor="settings-budget" className="text-[10px] uppercase tracking-widest text-text-secondary">Presupuesto Global (USD)</label>
                                            <input
                                                id="settings-budget"
                                                type="number"
                                                value={economyConfig.global_budget_usd ?? ''}
                                                onChange={(e) => setEconomyConfig({ ...economyConfig, global_budget_usd: e.target.value ? Number(e.target.value) : null })}
                                                className="mt-1 w-full bg-surface-3 border border-border-primary rounded px-2 py-1 text-xs text-text-primary"
                                            />
                                        </div>
                                        <div className="rounded-xl border border-border-primary bg-surface-1 p-3">
                                            <label htmlFor="settings-cache-ttl" className="text-[10px] uppercase tracking-widest text-text-secondary">TTL Cache (h)</label>
                                            <input
                                                id="settings-cache-ttl"
                                                type="number"
                                                value={economyConfig.cache_ttl_hours}
                                                onChange={(e) => setEconomyConfig({ ...economyConfig, cache_ttl_hours: Number(e.target.value) || 0 })}
                                                className="mt-1 w-full bg-surface-3 border border-border-primary rounded px-2 py-1 text-xs text-text-primary"
                                            />
                                        </div>
                                        <div className="rounded-xl border border-border-primary bg-surface-1 p-3">
                                            <div className="text-[10px] uppercase tracking-widest text-text-secondary">Indicadores</div>
                                            <div className="mt-1 space-y-1 text-xs text-text-primary">
                                                <label className="flex items-center gap-2">
                                                    <input type="checkbox" checked={economyConfig.cache_enabled} onChange={(e) => setEconomyConfig({ ...economyConfig, cache_enabled: e.target.checked })} /> cache
                                                </label>
                                                <label className="flex items-center gap-2">
                                                    <input type="checkbox" checked={economyConfig.show_cost_predictions} onChange={(e) => setEconomyConfig({ ...economyConfig, show_cost_predictions: e.target.checked })} /> predicciones
                                                </label>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <button onClick={saveEconomy} disabled={economySaving} className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-accent-purple/15 text-accent-purple border border-accent-purple/30 hover:bg-accent-purple/25 disabled:opacity-50">Guardar Economia</button>
                                        {economyMessage && <span className="text-xs text-text-secondary">{economyMessage}</span>}
                                        <button onClick={onOpenMastery} className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-surface-3 text-text-secondary border border-border-primary hover:text-text-primary">Panel de Economia <ArrowRight size={12} /></button>
                                    </div>
                                </div>
                            ) : (
                                <p className="text-xs text-text-secondary">Configuracion de Economia no disponible.</p>
                            )}
                        </section>
                    )}

                    {activeSection === 'security' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Shield size={16} className="text-accent-warning" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">Seguridad</h2>
                            </div>
                            <p className="text-xs text-text-secondary">
                                Las politicas, interruptores de circuito y dimensiones de confianza se gestionan desde la vista de Seguridad.
                            </p>
                            <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                                <SettingCell label="HITL" value="Activo" />
                                <SettingCell label="Role Profiles" value="3 (explorer, auditor, executor)" />
                                <SettingCell label="Circuit Breaker" value={realtimeMetrics ? `${realtimeMetrics.circuit_opens ?? 0} opens` : '—'} />
                            </div>
                        </section>
                    )}

                    {activeSection === 'maintenance' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Wrench size={16} className="text-orange-400" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">Mantenimiento</h2>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
                                <SettingCell label="CPU" value={hwMetrics ? `${hwMetrics.cpu_percent?.toFixed(1)}%` : '—'} />
                                <SettingCell label="RAM" value={hwMetrics ? `${hwMetrics.ram_percent?.toFixed(1)}%` : '—'} />
                                <SettingCell label="GPU VRAM Free" value={hwMetrics ? `${hwMetrics.gpu_vram_free_gb?.toFixed(1)} GB` : '—'} />
                                <SettingCell label="Load Level" value={hwMetrics?.load_level ?? '—'} />
                                <SettingCell label="SSE Subscribers" value={String(realtimeMetrics?.subscribers ?? '—')} />
                                <SettingCell label="Events Published" value={String(realtimeMetrics?.published ?? '—')} />
                                <SettingCell label="Events Dropped" value={String(realtimeMetrics?.dropped ?? '—')} />
                                <SettingCell label="Coalesced" value={String(realtimeMetrics?.coalesced ?? '—')} />
                                <SettingCell label="Forced Disconnects" value={String(realtimeMetrics?.forced_disconnects ?? '—')} />
                            </div>
                            <p className="text-[11px] text-text-secondary mt-3">
                                SSE subscribers = clientes en vivo conectados al stream de eventos. Coalesced = eventos agrupados para reducir ruido.
                            </p>
                        </section>
                    )}

                    {activeSection === 'language' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Globe size={16} className="text-accent-trust" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">{t('settings.language')}</h2>
                            </div>
                            <div className="flex gap-3">
                                <button
                                    onClick={() => i18n.changeLanguage('en')}
                                    className={`px-4 py-2 rounded-lg text-xs font-medium transition-colors ${i18n.language === 'en' ? 'bg-accent-primary text-white' : 'bg-surface-3 text-text-secondary hover:bg-surface-3/80'}`}
                                >
                                    {t('settings.english')}
                                </button>
                                <button
                                    onClick={() => i18n.changeLanguage('es')}
                                    className={`px-4 py-2 rounded-lg text-xs font-medium transition-colors ${i18n.language === 'es' ? 'bg-accent-primary text-white' : 'bg-surface-3 text-text-secondary hover:bg-surface-3/80'}`}
                                >
                                    {t('settings.spanish')}
                                </button>
                            </div>
                        </section>
                    )}

                    {activeSection === 'about' && (
                        <section className="rounded-2xl border border-border-primary bg-surface-2 p-5">
                            <div className="flex items-center gap-2 mb-4">
                                <Info size={16} className="text-accent-trust" />
                                <h2 className="text-sm font-black uppercase tracking-widest text-text-primary">Acerca de</h2>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                                <SettingCell label="Version" value={statusInfo?.version ?? '—'} />
                                <SettingCell label="Uptime" value={formatUptime(statusInfo?.uptime_seconds)} />
                                <SettingCell label="Endpoints" value="/ops/*" />
                            </div>
                        </section>
                    )}

                </div>
            </div>
        </div>
    );
};

const SettingCell: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <div className="rounded-xl border border-border-primary bg-surface-1 p-3">
        <div className="text-[10px] uppercase tracking-widest text-text-secondary mb-1">{label}</div>
        <div className="text-text-primary font-medium">{value}</div>
    </div>
);

const ToggleCell: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void }> = ({ label, checked, onChange }) => (
    <div className="rounded-xl border border-border-primary bg-surface-1 p-3 flex items-center justify-between">
        <div>
            <div className="text-[10px] uppercase tracking-widest text-text-secondary mb-1">{label}</div>
            <div className="text-text-primary font-medium text-xs">{checked ? 'activado' : 'desactivado'}</div>
        </div>
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${checked ? 'bg-accent-primary' : 'bg-surface-3'}`}
        >
            <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0'}`} />
        </button>
    </div>
);
