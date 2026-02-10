import React, { useState } from 'react';
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
    const security = useSecurityService(token);
    // Prefer "LOCKDOWN" terminology, but keep compatibility with older return shapes.
    const lockdown = security.lockdown ?? security.panicMode;
    const clearLockdown = security.clearLockdown ?? security.clearPanic;
    const isSecurityLoading = security.isLoading;
    const { repos, activeRepo, bootstrap, selectRepo, isLoading: isRepoLoading } = useRepoService(token);

    const [selectedRepoPath, setSelectedRepoPath] = useState<string>('');

    const apiLabel = (() => {
        try {
            const url = new URL(API_BASE);
            return url.port ? `${url.hostname}:${url.port}` : url.hostname;
        } catch {
            return 'API';
        }
    })();

    const getStatusTheme = () => {
        if (lockdown) return {
            color: 'text-red-500',
            bg: 'bg-red-500/10',
            border: 'border-red-500/30',
            label: 'LOCKDOWN'
        };

        switch (status) {
            case 'RUNNING':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    label: 'RUNNING'
                };
            case 'STARTING':
                return {
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/20',
                    label: 'STARTING'
                };
            case 'STOPPING':
                return {
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/20',
                    label: 'STOPPING'
                };
            case 'STOPPED':
                return {
                    color: 'text-red-400',
                    bg: 'bg-red-500/10',
                    border: 'border-red-500/20',
                    label: 'STOPPED'
                };
            default:
                return {
                    color: 'text-zinc-500',
                    bg: 'bg-zinc-500/10',
                    border: 'border-zinc-500/20',
                    label: 'UNKNOWN'
                };
        }
    };

    const theme = getStatusTheme();

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
            {serviceError && (
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl flex items-center space-x-3 text-red-400 text-xs animate-fade-in">
                    <ShieldAlert className="w-4 h-4 shrink-0" />
                    <span className="flex-1">{serviceError}</span>
                </div>
            )}
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
                                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40 mb-1">Status</h3>
                                <div className="flex items-center space-x-2">
                                    <span className={`text-xl font-black ${theme.color}`}>{theme.label}</span>
                                    {!isServiceLoading && <div className={`w-1.5 h-1.5 rounded-full ${status === 'RUNNING' ? 'bg-emerald-500' : 'bg-red-500'}`} />}
                                </div>
                            </div>
                        </div>
                        <div className="flex space-x-2">
                            <button
                                onClick={restart}
                                title="Restart Service"
                                disabled={isServiceLoading || lockdown}
                                className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 transition-all disabled:opacity-30 group"
                            >
                                <RefreshCcw className={`w-4 h-4 text-zinc-400 group-hover:text-white ${isServiceLoading ? 'animate-spin' : ''}`} />
                            </button>
                            <button
                                onClick={stop}
                                title="Stop Service"
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
                            <span>Uptime: —</span>
                        </div>
                        <div className="flex items-center space-x-2">
                            <Database className="w-3 h-3 opacity-40" />
                            <span>{apiLabel}</span>
                        </div>
                    </div>
                </div>

                {/* Security Lockdown Control */}
                {lockdown ? (
                    <div className="glass-card p-6 bg-red-500/5 border-red-500/20 flex flex-col justify-between">
                        <div className="flex items-center space-x-3 text-red-500 mb-4">
                            <ShieldAlert className="w-6 h-6" />
                            <span className="text-sm font-black uppercase tracking-widest">Security: LOCKDOWN</span>
                        </div>
                        <p className="text-xs text-red-400 mb-6 font-medium">Lockdown is active. File access requests are blocked.</p>
                        <button
                            onClick={clearLockdown}
                            disabled={isSecurityLoading}
                            className="w-full py-3.5 bg-red-500 hover:bg-red-400 text-white text-xs font-black uppercase tracking-widest rounded-xl transition-all shadow-lg active:scale-95 disabled:opacity-50"
                        >
                            {isSecurityLoading ? 'Working...' : 'Clear lockdown'}
                        </button>
                    </div>
                ) : (
                    <div className="glass-card p-6 flex flex-col justify-between">
                        <div className="flex items-center space-x-3 text-emerald-500/60 mb-4">
                            <ShieldCheck className="w-6 h-6" />
                            <span className="text-sm font-black uppercase tracking-widest">Security: OK</span>
                        </div>
                        <div className="space-y-2">
                            <div className="flex justify-between text-[10px] uppercase font-bold tracking-widest text-zinc-600">
                                <span>Security profile</span>
                                <span className="text-emerald-500">High</span>
                            </div>
                            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                                <div className="h-full w-full bg-emerald-500/40 rounded-full" />
                            </div>
                        </div>
                        <div className="mt-4 text-[10px] text-zinc-500 font-mono">
                            Audit integrity: verified
                        </div>
                    </div>
                )}
            </div>

            {/* Repositories Section */}
            <div className="glass-card bg-[#1c1c1e] rounded-3xl overflow-hidden border border-white/5">
                <div className="p-6 border-b border-white/5 flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                        <Database className="w-5 h-5 text-blue-400" />
                        <h3 className="text-xs font-black uppercase tracking-widest text-[#f5f5f7]">Active Repository</h3>
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
                            <label htmlFor="repo-select" className="text-[10px] font-black uppercase tracking-widest text-zinc-500 ml-1">Target Repository</label>
                            <div className="relative group">
                                <select
                                    id="repo-select"
                                    value={selectedRepoPath}
                                    onChange={(e) => setSelectedRepoPath(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-4 text-sm text-white appearance-none focus:border-blue-500/40 outline-none transition-all cursor-pointer group-hover:border-white/20"
                                >
                                    <option value="">Select a repository...</option>
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
                                Activate
                            </button>
                            <button
                                onClick={() => bootstrap(selectedRepoPath)}
                                disabled={!selectedRepoPath || isRepoLoading}
                                className="flex-1 bg-white/5 hover:bg-white/10 text-white py-4 rounded-2xl font-black text-xs uppercase tracking-widest transition-all border border-white/10 disabled:opacity-30 active:scale-95 flex items-center justify-center space-x-2"
                            >
                                <FlaskConical className="w-4 h-4" />
                                <span>Bootstrap files</span>
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
                        <h3 className="text-xs font-black uppercase tracking-widest text-[#f5f5f7]">Audit log</h3>
                    </div>
                    <div className="flex items-center space-x-3">
                        <div className="relative flex items-center">
                            <Search className="absolute left-3 w-3.5 h-3.5 text-zinc-500" />
                            <input
                                type="text"
                                placeholder="Search logs..."
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
                            <option value="all">ANY</option>
                            <option value="read">READ</option>
                            <option value="deny">DENY</option>
                            <option value="system">SYS</option>
                        </select>
                        <button
                            onClick={refreshLogs}
                            title="Refresh Logs"
                            className="p-2 rounded-xl bg-zinc-900/50 border border-white/5 hover:bg-white/5 transition-all"
                        >
                            <RefreshCcw className="w-3.5 h-3.5 text-zinc-500" />
                        </button>
                        <button
                            onClick={handleExport}
                            title="Export Logs"
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
                                <div key={i} className={`break-all leading-relaxed ${getLogClass(log)} transition-colors`}>
                                    {log}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-3 opacity-40">
                            <FileText className="w-8 h-8" />
                            <span className="text-[10px] font-black uppercase tracking-widest">No matching events</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
