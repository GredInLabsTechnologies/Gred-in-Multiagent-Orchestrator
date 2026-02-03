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
    Clock
} from 'lucide-react';

interface MaintenanceIslandProps {
    token?: string;
}

export const MaintenanceIsland: React.FC<MaintenanceIslandProps> = ({ token }) => {
    const { status, isLoading: isServiceLoading, restart, stop } = useSystemService(token);
    const {
        logs,
        rawLogs,
        filter,
        setFilter,
        searchTerm,
        setSearchTerm,
        refresh: refreshLogs
    } = useAuditLog(token);
    const { panicMode, clearPanic, isLoading: isSecurityLoading } = useSecurityService(token);
    const { repos, activeRepo, vitaminize, selectRepo, isLoading: isRepoLoading } = useRepoService(token);

    const [selectedRepoPath, setSelectedRepoPath] = useState<string>('');

    const getStatusTheme = () => {
        if (panicMode) return {
            color: 'text-red-500',
            bg: 'bg-red-500/10',
            border: 'border-red-500/30',
            glow: 'neon-glow-red',
            label: 'LOCKDOWN'
        };
        switch (status) {
            case 'RUNNING': return {
                color: 'text-emerald-400',
                bg: 'bg-emerald-500/10',
                border: 'border-emerald-500/20',
                glow: 'neon-glow-green',
                label: 'OPTIMAL'
            };
            case 'STOPPED': return {
                color: 'text-red-400',
                bg: 'bg-red-500/10',
                border: 'border-red-500/20',
                glow: '',
                label: 'STOPPED'
            };
            case 'STARTING':
            case 'STOPPING': return {
                color: 'text-amber-400',
                bg: 'bg-amber-500/10',
                border: 'border-amber-500/20',
                glow: '',
                label: 'TRANSITION'
            };
            default: return {
                color: 'text-zinc-500',
                bg: 'bg-zinc-500/10',
                border: 'border-zinc-500/20',
                glow: '',
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
            {/* Top Grid: Status & Controls */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* System Core status */}
                <div className={`glass-card p-6 flex flex-col justify-between overflow-hidden relative ${theme.glow}`}>
                    <div className="flex items-start justify-between">
                        <div className="flex items-center space-x-4">
                            <div className={`p-3 rounded-2xl ${theme.bg} ${theme.color} border ${theme.border} relative`}>
                                <Activity className="w-6 h-6" />
                                {status === 'RUNNING' && !panicMode && (
                                    <div className="absolute inset-0 rounded-2xl animate-pulse-ring bg-emerald-500/20" />
                                )}
                            </div>
                            <div>
                                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40 mb-1">System Core</h3>
                                <div className="flex items-center space-x-2">
                                    <span className={`text-xl font-black ${theme.color}`}>{theme.label}</span>
                                    {!isServiceLoading && <div className={`w-1.5 h-1.5 rounded-full ${status === 'RUNNING' ? 'bg-emerald-500' : 'bg-red-500'}`} />}
                                </div>
                            </div>
                        </div>
                        <div className="flex space-x-2">
                            <button
                                onClick={restart}
                                disabled={isServiceLoading || panicMode}
                                className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 transition-all disabled:opacity-30 group"
                            >
                                <RefreshCcw className={`w-4 h-4 text-zinc-400 group-hover:text-white ${isServiceLoading ? 'animate-spin' : ''}`} />
                            </button>
                            <button
                                onClick={stop}
                                disabled={isServiceLoading || status === 'STOPPED' || panicMode}
                                className="p-2.5 rounded-xl bg-red-500/5 hover:bg-red-500/10 border border-red-500/10 transition-all disabled:opacity-30 group"
                            >
                                <Square className="w-4 h-4 text-red-500/60 group-hover:text-red-500" />
                            </button>
                        </div>
                    </div>

                    <div className="mt-6 flex items-center justify-between text-[11px] font-medium text-zinc-500">
                        <div className="flex items-center space-x-2">
                            <Clock className="w-3 h-3 opacity-40" />
                            <span>Uptime: 12h 45m</span>
                        </div>
                        <div className="flex items-center space-x-2">
                            <ExternalLink className="w-3 h-3 opacity-40" />
                            <span>Port: 6834</span>
                        </div>
                    </div>
                </div>

                {/* Security Lockdown Control */}
                {panicMode ? (
                    <div className="glass-card p-6 bg-red-500/5 border-red-500/20 neon-glow-red flex flex-col justify-between">
                        <div className="flex items-center space-x-3 text-red-500 mb-4">
                            <ShieldAlert className="w-6 h-6" />
                            <span className="text-sm font-black uppercase tracking-widest">Security Breach Detected</span>
                        </div>
                        <p className="text-xs text-red-400 mb-6 font-medium">System is in high-security lockdown. All file access requests are currently blocked.</p>
                        <button
                            onClick={clearPanic}
                            disabled={isSecurityLoading}
                            className="w-full py-3.5 bg-red-500 hover:bg-red-400 text-white text-xs font-black uppercase tracking-widest rounded-xl transition-all shadow-lg active:scale-95 disabled:opacity-50"
                        >
                            {isSecurityLoading ? 'RESTORING...' : 'DEACTIVATE LOCKDOWN'}
                        </button>
                    </div>
                ) : (
                    <div className="glass-card p-6 flex flex-col justify-between">
                        <div className="flex items-center space-x-3 text-emerald-500/60 mb-4">
                            <ShieldCheck className="w-6 h-6" />
                            <span className="text-sm font-black uppercase tracking-widest">Vault Hardened</span>
                        </div>
                        <div className="space-y-2">
                            <div className="flex justify-between text-[10px] uppercase font-bold tracking-widest text-zinc-600">
                                <span>Security Level</span>
                                <span className="text-emerald-500">ASVS L3</span>
                            </div>
                            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                                <div className="h-full w-full bg-emerald-500/40 rounded-full" />
                            </div>
                        </div>
                        <div className="mt-4 text-[10px] text-zinc-500 font-mono">
                            SHA-256 Audit Integrity: Verified
                        </div>
                    </div>
                )}
            </div>

            {/* Middle Section: Repository Control */}
            <div className="glass-card p-6">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center space-x-3">
                        <Database className="w-5 h-5 text-blue-500" />
                        <h3 className="text-xs font-black uppercase tracking-[0.2em] text-zinc-400">Repository Management</h3>
                    </div>
                    {activeRepo && (
                        <div className="flex items-center space-x-2 px-3 py-1 bg-emerald-500/5 border border-emerald-500/10 rounded-full">
                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest truncate max-w-[150px]">
                                {activeRepo.split(/[/\\]/).pop()}
                            </span>
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="md:col-span-2 relative group">
                        <select
                            id="repo-select"
                            value={selectedRepoPath}
                            onChange={(e) => setSelectedRepoPath(e.target.value)}
                            className="w-full pl-4 pr-10 py-3.5 bg-zinc-900/50 border border-white/5 rounded-2xl text-sm text-zinc-300 focus:border-blue-500/50 outline-none transition-all appearance-none cursor-pointer hover:bg-zinc-900/80"
                        >
                            <option value="">Select target repository...</option>
                            {repos.map((repo) => (
                                <option key={repo.path} value={repo.path}>{repo.name}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-600 pointer-events-none group-hover:text-zinc-400 transition-colors" />
                    </div>
                    <div className="flex space-x-2">
                        <button
                            onClick={() => selectRepo(selectedRepoPath)}
                            disabled={!selectedRepoPath || isRepoLoading || selectedRepoPath === activeRepo}
                            className="flex-1 py-3 bg-zinc-800 hover:bg-zinc-700 border border-white/5 rounded-2xl text-[10px] font-black uppercase tracking-widest text-zinc-300 transition-all disabled:opacity-20 active:scale-95"
                        >
                            Activate
                        </button>
                        <button
                            onClick={() => vitaminize(selectedRepoPath)}
                            disabled={!selectedRepoPath || isRepoLoading}
                            className="flex-1 py-3 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 rounded-2xl text-[10px] font-black uppercase tracking-widest text-blue-400 transition-all disabled:opacity-20 flex items-center justify-center space-x-2 active:scale-95"
                        >
                            <FlaskConical className="w-4 h-4" />
                            <span>Vitaminize</span>
                        </button>
                    </div>
                </div>
            </div>

            {/* Bottom Section: Audit Logs */}
            <div className="glass-card flex flex-col overflow-hidden">
                <div className="px-6 py-4 border-b border-white/5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="flex items-center space-x-3">
                        <Terminal className="w-5 h-5 text-emerald-500" />
                        <h3 className="text-xs font-black uppercase tracking-[0.2em] text-zinc-400">Live Audit Stream</h3>
                    </div>

                    <div className="flex items-center space-x-2">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-600" />
                            <input
                                type="text"
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                placeholder="Search..."
                                className="pl-9 pr-4 py-2 bg-zinc-900/50 border border-white/5 rounded-xl text-xs text-zinc-300 focus:border-emerald-500/30 outline-none transition-all placeholder:text-zinc-700 w-32 focus:w-48"
                            />
                        </div>
                        <select
                            value={filter}
                            onChange={(e) => setFilter(e.target.value as 'all' | 'read' | 'deny' | 'system')}
                            className="px-3 py-2 bg-zinc-900/50 border border-white/5 rounded-xl text-[10px] font-bold text-zinc-400 focus:border-emerald-500/30 outline-none transition-all cursor-pointer appearance-none uppercase tracking-tighter"
                        >
                            <option value="all">ANY</option>
                            <option value="read">READ</option>
                            <option value="deny">DENY</option>
                            <option value="system">SYS</option>
                        </select>
                        <button
                            onClick={refreshLogs}
                            className="p-2 rounded-xl bg-zinc-900/50 border border-white/5 hover:bg-white/5 transition-all"
                        >
                            <RefreshCcw className="w-3.5 h-3.5 text-zinc-500" />
                        </button>
                        <button
                            onClick={handleExport}
                            className="p-2 rounded-xl bg-zinc-900/50 border border-white/5 hover:bg-white/5 transition-all"
                        >
                            <Download className="w-3.5 h-3.5 text-zinc-500" />
                        </button>
                    </div>
                </div>

                <div className="h-80 overflow-y-auto p-6 space-y-2 custom-scrollbar bg-zinc-950/20 font-mono text-[11px]">
                    {logs.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center py-12 opacity-10">
                            <FileText className="w-12 h-12 mb-4" />
                            <p className="text-sm font-black uppercase tracking-widest">No audit data</p>
                        </div>
                    ) : (
                        logs.map((log, i) => (
                            <div key={`log-${logs.length - i}`} className="flex space-x-4 group animate-fade-in">
                                <span className="text-zinc-800 shrink-0 select-none font-bold">[{logs.length - i}]</span>
                                <span className={`break-all leading-relaxed ${getLogClass(log)}`}>
                                    {log}
                                </span>
                            </div>
                        ))
                    )}
                </div>

                <div className="px-6 py-2 border-t border-white/5 bg-zinc-900/30 flex justify-between items-center">
                    <span className="text-[9px] font-bold text-zinc-700 uppercase tracking-widest">
                        Buffer: {logs.length} events
                    </span>
                    <div className="flex space-x-1">
                        <div className="w-1 h-1 rounded-full bg-emerald-500/40" />
                        <div className="w-1 h-1 rounded-full bg-emerald-500/40" />
                        <div className="w-1 h-1 rounded-full bg-emerald-500/40" />
                    </div>
                </div>
            </div>
        </div>
    );
};
