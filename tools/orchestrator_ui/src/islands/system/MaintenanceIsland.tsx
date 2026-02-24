import React, { useEffect, useState } from 'react';
import { useSystemService } from '../../hooks/useSystemService';
import { useAuditLog } from '../../hooks/useAuditLog';
import { useSecurityService } from '../../hooks/useSecurityService';
import { useRepoService } from '../../hooks/useRepoService';
import {
    Activity,
    RefreshCcw,
    Square,
    FileText,
    Search,
    ChevronDown,
    Terminal,
    ShieldCheck,
    Download,
    FlaskConical,
    ShieldAlert,
    Database,
    ExternalLink,
    Clock,
} from 'lucide-react';

import { API_BASE } from '../../types';

interface MaintenanceIslandProps {
    token?: string;
}

type AuditFilter = 'all' | 'read' | 'deny' | 'system';

export const MaintenanceIsland: React.FC<MaintenanceIslandProps> = ({ token }) => {
    const { status, isLoading: isServiceLoading, error: serviceError, restart, stop } = useSystemService(token);
    const {
        logs,
        rawLogs,
        filter,
        setFilter,
        searchTerm,
        setSearchTerm,
        refresh: refreshLogs
    } = useAuditLog(token);
    const {
        threatLevel,
        threatLevelLabel,
        autoDecayRemaining,
        activeSources,
        lockdown,
        isLoading: isSecurityLoading,
        clearLockdown,
        downgrade,
        error: securityError
    } = useSecurityService(token);

    const { repos, activeRepo, bootstrap, selectRepo, isLoading: isRepoLoading } = useRepoService(token);

    const [selectedRepoPath, setSelectedRepoPath] = useState<string>('');
    const [uptimeLabel, setUptimeLabel] = useState<string>('—');

    useEffect(() => {
        let cancelled = false;

        const formatUptime = (uptimeSeconds: number): string => {
            if (!Number.isFinite(uptimeSeconds) || uptimeSeconds < 0) return '—';
            const total = Math.floor(uptimeSeconds);
            const days = Math.floor(total / 86400);
            const hours = Math.floor((total % 86400) / 3600);
            const minutes = Math.floor((total % 3600) / 60);
            const seconds = total % 60;

            if (days > 0) return `${days}d ${hours}h`;
            if (hours > 0) return `${hours}h ${minutes}m`;
            if (minutes > 0) return `${minutes}m ${seconds}s`;
            return `${seconds}s`;
        };

        const fetchUiStatus = async () => {
            try {
                const response = await fetch(`${API_BASE}/ui/status`, {
                    credentials: 'include',
                });
                if (!response.ok) {
                    if (!cancelled) setUptimeLabel('—');
                    return;
                }

                const data = await response.json() as { uptime_seconds?: number };
                if (!cancelled) {
                    setUptimeLabel(formatUptime(data.uptime_seconds ?? Number.NaN));
                }
            } catch {
                if (!cancelled) setUptimeLabel('—');
            }
        };

        fetchUiStatus();
        const interval = setInterval(fetchUiStatus, 10000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);

    const apiLabel = (() => {
        try {
            const url = new URL(API_BASE);
            return url.port ? `${url.hostname}:${url.port}` : url.hostname;
        } catch {
            return 'API';
        }
    })();

    const getSecurityTheme = () => {
        switch (threatLevel) {
            case 3: // LOCKDOWN
                return {
                    color: 'text-red-500',
                    bg: 'bg-red-500/10',
                    border: 'border-red-500/30',
                    bar: 'bg-red-500',
                    icon: <ShieldAlert className="w-6 h-6" />,
                    message: 'BLOQUEO PROTECTIVO: Tráfico anónimo bloqueado.'
                };
            case 2: // GUARDED
                return {
                    color: 'text-orange-500',
                    bg: 'bg-orange-500/10',
                    border: 'border-orange-500/30',
                    bar: 'bg-orange-500',
                    icon: <ShieldAlert className="w-6 h-6" />,
                    message: 'PROTEGIDO: Latencia forzada para peticiones no autenticadas.'
                };
            case 1: // ALERT
                return {
                    color: 'text-amber-500',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/30',
                    bar: 'bg-amber-500',
                    icon: <Activity className="w-6 h-6" />,
                    message: 'ALERTA: Actividad sospechosa detectada. Monitoreando fuentes.'
                };
            default: // NOMINAL
                return {
                    color: 'text-emerald-500',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    bar: 'bg-emerald-500',
                    icon: <ShieldCheck className="w-6 h-6" />,
                    message: 'NOMINAL: Seguridad del sistema dentro de parámetros normales.'
                };
        }
    };

    const getStatusTheme = () => {
        if (lockdown) return {
            color: 'text-red-500',
            bg: 'bg-red-500/10',
            border: 'border-red-500/30',
            label: 'BLOQUEO'
        };

        switch (status) {
            case 'RUNNING':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    label: 'EJECUTANDO'
                };
            case 'STARTING':
                return {
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/20',
                    label: 'INICIANDO'
                };
            case 'STOPPING':
                return {
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/20',
                    label: 'DETENIENDO'
                };
            case 'STOPPED':
                return {
                    color: 'text-red-400',
                    bg: 'bg-red-500/10',
                    border: 'border-red-500/20',
                    label: 'DETENIDO'
                };
            default:
                return {
                    color: 'text-zinc-500',
                    bg: 'bg-zinc-500/10',
                    border: 'border-zinc-500/20',
                    label: 'DESCONOCIDO'
                };
        }
    };

    const theme = getStatusTheme();
    const sTheme = getSecurityTheme();

    const formatDecay = (seconds: number | null | undefined) => {
        if (seconds === null || seconds === undefined) return null;
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    const getLogClass = (log: string): string => {
        if (log.includes('DENIED')) return 'text-red-400 bg-red-400/5 px-2 rounded border border-red-500/10';
        if (log.includes('READ')) return 'text-blue-400';
        if (log.includes('SYSTEM')) return 'text-amber-400';
        return 'text-zinc-400';
    };

    const handleExport = () => {
        if (rawLogs.length === 0) return;
        const blob = new Blob([rawLogs.join('\n')], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `gred_audit_${new Date().toISOString().replaceAll(/[:.]/g, '-')}.log`;
        link.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="flex flex-col space-y-8">
            {(serviceError || securityError) && (
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl flex items-center space-x-3 text-red-400 text-xs animate-fade-in">
                    <ShieldAlert className="w-4 h-4 shrink-0" />
                    <span className="flex-1">{serviceError || securityError}</span>
                </div>
            )}

            <div className="p-3 rounded-xl border border-[#2c2c2e] bg-[#141414] text-xs text-[#86868b]">
                <strong className="text-[#f5f5f7]">Nota:</strong> <span className="text-[#f5f5f7]">Estado</span> (servicio EJECUTANDO/DETENIDO)
                {' '}y <span className="text-[#f5f5f7]">Nivel de Seguridad</span> (NOMINAL/ALERTA/PROTEGIDO/BLOQUEO) son métricas independientes.
            </div>

            {/* Top Grid: Status & Controls */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* System Core status */}
                <div className={`glass-card p-6 flex flex-col justify-between overflow-hidden relative`}>
                    <div className="flex items-start justify-between">
                        <div className="flex items-center space-x-4">
                            <div className={`p-3 rounded-2xl ${theme.bg} ${theme.color} border ${theme.border} relative`}>
                                <Activity className="w-6 h-6" />
                                {status === 'RUNNING' && !lockdown && (
                                    <div className="absolute inset-0 rounded-2xl animate-pulse-ring bg-emerald-500/20" />
                                )}
                            </div>
                            <div>
                                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40 mb-1">Estado</h3>
                                <div className="flex items-center space-x-2">
                                    <span className={`text-xl font-black ${theme.color}`}>{theme.label}</span>
                                    {!isServiceLoading && <div className={`w-1.5 h-1.5 rounded-full ${status === 'RUNNING' ? 'bg-emerald-500' : 'bg-red-500'}`} />}
                                </div>
                            </div>
                        </div>
                        <div className="flex space-x-2">
                            <button
                                onClick={restart}
                                title="Reiniciar Servicio"
                                disabled={isServiceLoading || lockdown}
                                className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 transition-all disabled:opacity-30 group"
                            >
                                <RefreshCcw className={`w-4 h-4 text-zinc-400 group-hover:text-white ${isServiceLoading ? 'animate-spin' : ''}`} />
                            </button>
                            <button
                                onClick={stop}
                                title="Detener Servicio"
                                disabled={isServiceLoading || status === 'STOPPED' || lockdown}
                                className="p-2.5 rounded-xl bg-red-500/5 hover:bg-red-500/10 border border-red-500/10 transition-all disabled:opacity-30 group"
                            >
                                <Square className="w-4 h-4 text-red-500/60 group-hover:text-red-500" />
                            </button>
                        </div>
                    </div>
                    <div className="mt-6 flex items-center justify-between text-[11px] font-medium text-zinc-500">
                        <div className="flex items-center space-x-2">
                            <Clock className="w-3 h-3 opacity-40" />
                            <span>Actividad: {uptimeLabel}</span>
                        </div>
                        <div className="flex items-center space-x-2">
                            <Database className="w-3 h-3 opacity-40" />
                            <span>{apiLabel}</span>
                        </div>
                    </div>
                </div>

                {/* Adaptive Security Threat Level */}
                <div className={`glass-card p-6 border transition-all duration-500 ${sTheme.bg} ${sTheme.border} flex flex-col justify-between`}>
                    <div className="flex items-start justify-between">
                        <div className="flex items-center space-x-3">
                            <div className={`${sTheme.color}`}>
                                {sTheme.icon}
                            </div>
                            <div>
                                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40 mb-1">Nivel de Seguridad</h3>
                                <div className="flex items-center space-x-2">
                                    <span className={`text-xl font-black uppercase ${sTheme.color}`}>{threatLevelLabel}</span>
                                    {autoDecayRemaining !== null && (
                                        <div className="flex items-center space-x-1 px-2 py-0.5 bg-black/40 rounded-full border border-white/5 text-[9px] font-bold text-zinc-400">
                                            <Clock className="w-2.5 h-2.5" />
                                            <span>{formatDecay(autoDecayRemaining)}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                        {threatLevel > 0 && (
                            <div className="flex space-x-2">
                                <button
                                    onClick={downgrade}
                                    title="Bajar nivel de amenaza"
                                    disabled={isSecurityLoading}
                                    className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 transition-all disabled:opacity-30 group"
                                >
                                    <ChevronDown className="w-4 h-4 text-zinc-400 group-hover:text-white" />
                                </button>
                                <button
                                    onClick={clearLockdown}
                                    title="Restablecer a NOMINAL"
                                    disabled={isSecurityLoading}
                                    className="p-2.5 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/10 transition-all disabled:opacity-30 group"
                                >
                                    <ShieldCheck className="w-4 h-4 text-emerald-500/60 group-hover:text-emerald-500" />
                                </button>
                            </div>
                        )}
                    </div>

                    <div className="flex-1 mt-4">
                        <p className={`text-[11px] font-medium leading-relaxed opacity-80 ${sTheme.color}`}>
                            {sTheme.message}
                        </p>
                    </div>

                    <div className="mt-4 space-y-2">
                        <div className="flex justify-between text-[9px] uppercase font-black tracking-widest text-zinc-500">
                            <span>Intensidad de amenaza</span>
                            <span className={sTheme.color}>{activeSources > 0 ? `${activeSources} fuentes rastreadas` : 'Verificado'}</span>
                        </div>
                        <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden border border-white/5">
                            <div
                                className={`h-full transition-all duration-1000 ease-out rounded-full ${sTheme.bar}`}
                                style={{ width: `${Math.max(10, (threatLevel / 3) * 100)}%` }}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* Repositories Section */}
            <div className="glass-card bg-[#1c1c1e] rounded-3xl overflow-hidden border border-white/5">
                <div className="p-6 border-b border-white/5 flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                        <Database className="w-5 h-5 text-blue-400" />
                        <h3 className="text-xs font-black uppercase tracking-widest text-[#f5f5f7]">Repositorio Activo</h3>
                    </div>
                    {activeRepo && (
                        <div className="flex items-center space-x-2 text-[10px] font-mono text-zinc-500 bg-black/40 px-3 py-1.5 rounded-lg border border-white/5">
                            <ExternalLink className="w-3 h-3 opacity-40" />
                            <span>{activeRepo}</span>
                        </div>
                    )}
                </div>
                <div className="p-8">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-end">
                        <div className="space-y-3">
                            <label htmlFor="repo-select" className="text-[10px] font-black uppercase tracking-widest text-zinc-500 ml-1">Repositorio Destino</label>
                            <div className="relative group">
                                <select
                                    id="repo-select"
                                    value={selectedRepoPath}
                                    onChange={(e) => setSelectedRepoPath(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 text-sm text-white appearance-none focus:border-blue-500/40 outline-none transition-all cursor-pointer group-hover:border-white/20"
                                >
                                    <option value="">Seleccionar un repositorio...</option>
                                    {repos.map((repo) => (
                                        <option key={repo.path} value={repo.path}>
                                            {repo.name} ({repo.path})
                                        </option>
                                    ))}
                                </select>
                                <ChevronDown className="absolute right-6 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none transition-transform group-hover:text-zinc-300" />
                            </div>
                        </div>
                        <div className="flex space-x-4">
                            <button
                                onClick={() => selectRepo(selectedRepoPath)}
                                disabled={!selectedRepoPath || isRepoLoading || selectedRepoPath === activeRepo}
                                className="flex-1 bg-blue-500 hover:bg-blue-400 text-white py-4 rounded-2xl font-black text-xs uppercase tracking-widest transition-all disabled:opacity-30 active:scale-95"
                            >
                                Activar
                            </button>
                            <button
                                onClick={() => bootstrap(selectedRepoPath)}
                                disabled={!selectedRepoPath || isRepoLoading}
                                className="flex-1 bg-white/5 hover:bg-white/10 text-white py-4 rounded-2xl font-black text-xs uppercase tracking-widest transition-all border border-white/10 disabled:opacity-30 active:scale-95 flex items-center justify-center space-x-2"
                            >
                                <FlaskConical className="w-4 h-4" />
                                <span>Inicializar archivos</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Audit Log Section */}
            <div className="glass-card bg-[#1c1c1e] rounded-3xl overflow-hidden border border-white/5 flex flex-col min-h-[500px]">
                <div className="p-6 border-b border-white/5 bg-white/[0.02] flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                        <Terminal className="w-5 h-5 text-amber-500" />
                        <h3 className="text-xs font-black uppercase tracking-widest text-[#f5f5f7]">Registro de auditoría</h3>
                    </div>
                    <div className="flex items-center space-x-3">
                        <div className="relative flex items-center">
                            <Search className="absolute left-3 w-3.5 h-3.5 text-zinc-500" />
                            <input
                                type="text"
                                placeholder="Buscar logs..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="bg-black/40 border border-white/5 rounded-xl pl-9 pr-4 py-2 text-xs text-zinc-300 focus:border-amber-500/40 outline-none w-48 transition-all"
                            />
                        </div>
                        <select
                            value={filter}
                            onChange={(e) => setFilter(e.target.value as AuditFilter)}
                            className="bg-black/40 border border-white/5 rounded-xl px-3 py-2 text-[10px] font-bold text-zinc-400 outline-none hover:border-white/10 transition-all uppercase"
                        >
                            <option value="all">CUALQUIERA</option>
                            <option value="read">LECTURA</option>
                            <option value="deny">DENEGAR</option>
                            <option value="system">SISTEMA</option>
                        </select>
                        <button
                            onClick={refreshLogs}
                            title="Refrescar Logs"
                            className="p-2 rounded-xl bg-zinc-900/50 border border-white/5 hover:bg-white/5 transition-all"
                        >
                            <RefreshCcw className="w-3.5 h-3.5 text-zinc-500" />
                        </button>
                        <button
                            onClick={handleExport}
                            title="Exportar Logs"
                            className="p-2 rounded-xl bg-zinc-900/50 border border-white/5 hover:bg-white/5 transition-all"
                        >
                            <Download className="w-3.5 h-3.5 text-zinc-500" />
                        </button>
                    </div>
                </div>

                <div className="flex-1 p-6 font-mono text-[11px] overflow-y-auto bg-black/20 custom-scrollbar">
                    {logs.length > 0 ? (
                        <div className="space-y-1.5">
                            {logs.map((log, i) => (
                                <div key={`${i}-${log.slice(0, 10)}`} className={`break-all leading-relaxed ${getLogClass(log)} transition-colors`}>
                                    {log}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-3 opacity-40">
                            <FileText className="w-8 h-8" />
                            <span className="text-[10px] font-black uppercase tracking-widest">No hay eventos coincidentes</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
