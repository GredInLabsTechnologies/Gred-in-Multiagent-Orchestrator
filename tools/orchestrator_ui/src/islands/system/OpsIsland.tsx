import React, { useState } from 'react';
import { useOpsService } from '../../hooks/useOpsService';
// types imported via useOpsService hook
import {
    Cpu, FileCode, Play, CheckCircle2, Clock, AlertCircle,
    Send, History, FileEdit, Terminal, ChevronRight, X,
    Ban, Settings, RefreshCw, Eye, Shield
} from 'lucide-react';

type Tab = 'plan' | 'drafts' | 'approved' | 'runs' | 'config';

interface OpsIslandProps {
    token?: string;
}

export const OpsIsland: React.FC<OpsIslandProps> = ({ token }) => {
    const {
        plan, drafts, approved, runs, config, isLoading, error,
        generateDraft, approveDraft, rejectDraft, startRun, cancelRun,
        updateConfig, refresh
    } = useOpsService(token);

    const [activeTab, setActiveTab] = useState<Tab>('plan');
    const [prompt, setPrompt] = useState('');
    const [autoRunToggle, setAutoRunToggle] = useState(false);
    const [expandedRun, setExpandedRun] = useState<string | null>(null);
    const [previewDraft, setPreviewDraft] = useState<string | null>(null);

    const handleGenerate = async () => {
        if (!prompt.trim()) return;
        await generateDraft(prompt);
        setPrompt('');
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'done': return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
            case 'approved': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
            case 'in_progress':
            case 'running': return <Clock className="w-4 h-4 text-amber-500 animate-pulse" />;
            case 'pending': return <Clock className="w-4 h-4 text-zinc-500" />;
            case 'cancelled': return <Ban className="w-4 h-4 text-zinc-500" />;
            case 'blocked':
            case 'error':
            case 'rejected': return <AlertCircle className="w-4 h-4 text-red-500" />;
            default: return <Clock className="w-4 h-4 text-zinc-600" />;
        }
    };

    const statusBadge = (status: string) => {
        const styles: Record<string, string> = {
            approved: 'bg-emerald-500/10 text-emerald-400',
            done: 'bg-emerald-500/10 text-emerald-400',
            draft: 'bg-blue-500/10 text-blue-400',
            pending: 'bg-amber-500/10 text-amber-400',
            running: 'bg-amber-500/10 text-amber-400',
            rejected: 'bg-red-500/10 text-red-400',
            error: 'bg-red-500/10 text-red-400',
            cancelled: 'bg-zinc-500/10 text-zinc-400',
        };
        return (
            <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full ${styles[status] || 'bg-white/5 text-zinc-400'}`}>
                {status}
            </span>
        );
    };

    const tabs: { key: Tab; label: string; count?: number }[] = [
        { key: 'plan', label: 'Plan' },
        { key: 'drafts', label: 'Drafts', count: drafts.filter(d => d.status === 'draft').length },
        { key: 'approved', label: 'Approved', count: approved.length },
        { key: 'runs', label: 'Runs', count: runs.filter(r => r.status === 'running' || r.status === 'pending').length },
        { key: 'config', label: 'Config' },
    ];

    return (
        <div className="flex flex-col space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                    <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
                        <Cpu className="w-5 h-5" />
                    </div>
                    <div>
                        <h2 className="text-sm font-black uppercase tracking-widest text-[#f5f5f7]">OPS Control Panel</h2>
                        <p className="text-[10px] text-[#86868b] font-medium">Multi-Agent Operations</p>
                    </div>
                </div>

                <div className="flex items-center space-x-3">
                    <button onClick={refresh} className="p-2 rounded-lg hover:bg-white/5 text-zinc-500 hover:text-zinc-300 transition-all" title="Refresh">
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                    </button>
                    <div className="flex bg-zinc-900/50 p-1 rounded-xl border border-white/5">
                        {tabs.map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => setActiveTab(tab.key)}
                                className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all flex items-center space-x-1.5 ${activeTab === tab.key
                                        ? 'bg-white/10 text-white shadow-lg'
                                        : 'text-zinc-500 hover:text-zinc-300'
                                    }`}
                            >
                                <span>{tab.label}</span>
                                {tab.count !== undefined && tab.count > 0 && (
                                    <span className="bg-white/10 px-1.5 py-0.5 rounded-full text-[8px]">{tab.count}</span>
                                )}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {error && (
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl flex items-center space-x-3 text-red-400 text-xs">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <span className="flex-1">{error}</span>
                </div>
            )}

            {/* ═══ PLAN TAB ═══ */}
            <div className="min-h-[400px]">
                {activeTab === 'plan' && (
                    <div className="space-y-6 animate-fade-in">
                        {plan ? (
                            <div className="glass-card p-6 bg-blue-500/5 border-blue-500/10 rounded-2xl border bg-opacity-10 backdrop-blur-md">
                                <div className="flex justify-between items-start mb-4">
                                    <div>
                                        <h3 className="text-lg font-bold text-white mb-1">{plan.title}</h3>
                                        <p className="text-xs text-zinc-400 max-w-2xl">{plan.objective}</p>
                                    </div>
                                    <div className="px-3 py-1 bg-blue-500/10 border border-blue-500/20 rounded-full text-[10px] font-bold text-blue-400">
                                        {plan.id}
                                    </div>
                                </div>
                                {plan.constraints.length > 0 && (
                                    <div className="mb-4 flex flex-wrap gap-2">
                                        {plan.constraints.map((c, i) => (
                                            <span key={i} className="px-2 py-1 bg-amber-500/10 border border-amber-500/20 rounded-lg text-[9px] text-amber-400">
                                                <Shield className="w-3 h-3 inline mr-1" />{c}
                                            </span>
                                        ))}
                                    </div>
                                )}
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                    {plan.tasks.map(task => (
                                        <div key={task.id} className="p-4 bg-black/20 border border-white/5 rounded-xl hover:border-white/10 transition-colors">
                                            <div className="flex items-center justify-between mb-2">
                                                <span className="text-[10px] font-mono text-zinc-500">{task.id}</span>
                                                {getStatusIcon(task.status)}
                                            </div>
                                            <h4 className="text-xs font-bold text-zinc-200 mb-1">{task.title}</h4>
                                            <p className="text-[10px] text-zinc-500 line-clamp-2">{task.description}</p>
                                            {task.depends.length > 0 && (
                                                <div className="mt-2 text-[9px] text-zinc-600">
                                                    deps: {task.depends.join(', ')}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <div className="h-64 flex flex-col items-center justify-center text-zinc-600">
                                <FileCode className="w-12 h-12 mb-4 opacity-20" />
                                <p className="text-xs font-black uppercase tracking-widest opacity-40">No active plan detected</p>
                            </div>
                        )}
                    </div>
                )}

                {/* ═══ DRAFTS TAB ═══ */}
                {activeTab === 'drafts' && (
                    <div className="space-y-6 animate-fade-in">
                        {/* Generate Prompt */}
                        <div className="glass-card p-6 bg-emerald-500/5 border-emerald-500/10 rounded-2xl border">
                            <div className="flex items-center space-x-3 mb-4 text-emerald-400">
                                <Send className="w-4 h-4" />
                                <span className="text-xs font-black uppercase tracking-widest">Generate Draft via LLM</span>
                            </div>
                            <div className="flex gap-4">
                                <input
                                    type="text"
                                    value={prompt}
                                    onChange={(e) => setPrompt(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
                                    placeholder="e.g. Implement the auth handshake for Task-1..."
                                    className="flex-1 bg-black/40 border border-white/5 rounded-2xl px-6 py-4 text-sm text-white focus:border-emerald-500/40 outline-none transition-all"
                                />
                                <button
                                    onClick={handleGenerate}
                                    disabled={isLoading || !prompt.trim()}
                                    className="bg-emerald-500 hover:bg-emerald-400 text-white px-8 rounded-2xl font-black text-xs uppercase tracking-widest transition-all disabled:opacity-30 active:scale-95 flex items-center space-x-2"
                                >
                                    {isLoading ? <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" /> : <ChevronRight className="w-4 h-4" />}
                                    <span>{isLoading ? 'Generating...' : 'Generate'}</span>
                                </button>
                            </div>
                        </div>

                        {/* Draft Filter Summary */}
                        <div className="flex items-center space-x-4 text-[10px] text-zinc-500">
                            <span>{drafts.length} total</span>
                            <span className="text-emerald-500">{drafts.filter(d => d.status === 'approved').length} approved</span>
                            <span className="text-blue-400">{drafts.filter(d => d.status === 'draft').length} pending</span>
                            <span className="text-red-400">{drafts.filter(d => d.status === 'rejected' || d.status === 'error').length} rejected/error</span>
                        </div>

                        {/* Draft Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {drafts.map(draft => (
                                <div key={draft.id} className="glass-card p-5 group border border-white/5 rounded-2xl bg-[#1c1c1e] hover:border-white/10 transition-colors">
                                    <div className="flex justify-between items-start mb-3">
                                        <div className="flex items-center space-x-2">
                                            <FileEdit className="w-3.5 h-3.5 text-zinc-400" />
                                            <span className="text-[10px] font-mono text-zinc-500">{draft.id}</span>
                                        </div>
                                        {statusBadge(draft.status)}
                                    </div>
                                    <p className="text-xs font-medium text-zinc-200 mb-2 line-clamp-2">"{draft.prompt}"</p>

                                    {/* Content Preview */}
                                    {draft.content && (
                                        <div className="mb-3">
                                            <button
                                                onClick={() => setPreviewDraft(previewDraft === draft.id ? null : draft.id)}
                                                className="text-[9px] text-blue-400 hover:text-blue-300 flex items-center space-x-1"
                                            >
                                                <Eye className="w-3 h-3" />
                                                <span>{previewDraft === draft.id ? 'Hide' : 'Preview'} content</span>
                                            </button>
                                            {previewDraft === draft.id && (
                                                <pre className="mt-2 p-3 bg-black/40 rounded-xl text-[10px] text-zinc-400 max-h-48 overflow-auto font-mono whitespace-pre-wrap">
                                                    {draft.content}
                                                </pre>
                                            )}
                                        </div>
                                    )}

                                    {draft.error && (
                                        <p className="text-[10px] text-red-400 mb-2">Error: {draft.error}</p>
                                    )}

                                    <div className="flex justify-between items-center">
                                        <span className="text-[9px] text-zinc-600">{new Date(draft.created_at).toLocaleString()}</span>
                                        <div className="flex space-x-2 shrink-0">
                                            {draft.status === 'draft' && (
                                                <>
                                                    <button
                                                        onClick={() => rejectDraft(draft.id)}
                                                        className="px-3 py-1 bg-red-500/10 text-red-400 rounded-lg text-[9px] font-black uppercase hover:bg-red-500/20 transition-all"
                                                    >
                                                        Reject
                                                    </button>
                                                    <div className="flex items-center space-x-1">
                                                        <label className="flex items-center space-x-1 text-[9px] text-zinc-500 cursor-pointer">
                                                            <input
                                                                type="checkbox"
                                                                checked={autoRunToggle}
                                                                onChange={(e) => setAutoRunToggle(e.target.checked)}
                                                                className="w-3 h-3 rounded"
                                                            />
                                                            <span>auto-run</span>
                                                        </label>
                                                        <button
                                                            onClick={() => approveDraft(draft.id, autoRunToggle)}
                                                            className="px-3 py-1 bg-emerald-500/20 text-emerald-400 rounded-lg text-[9px] font-black uppercase hover:bg-emerald-500/30 transition-all"
                                                        >
                                                            Approve
                                                        </button>
                                                    </div>
                                                </>
                                            )}
                                            {draft.status === 'approved' && (
                                                <button
                                                    onClick={() => {
                                                        const app = approved.find(a => a.draft_id === draft.id);
                                                        if (app) startRun(app.id);
                                                    }}
                                                    className="px-3 py-1 bg-blue-500/20 text-blue-400 rounded-lg text-[9px] font-black uppercase hover:bg-blue-500/30 transition-all flex items-center space-x-1"
                                                >
                                                    <Play className="w-2.5 h-2.5" />
                                                    <span>Deploy</span>
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ═══ APPROVED TAB ═══ */}
                {activeTab === 'approved' && (
                    <div className="space-y-4 animate-fade-in">
                        {approved.length > 0 ? (
                            approved.map(app => {
                                const hasRun = runs.some(r => r.approved_id === app.id);
                                return (
                                    <div key={app.id} className="p-5 border border-white/5 rounded-2xl bg-[#1c1c1e] hover:border-emerald-500/20 transition-colors">
                                        <div className="flex justify-between items-start mb-3">
                                            <div>
                                                <div className="flex items-center space-x-2 mb-1">
                                                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                                                    <span className="text-xs font-bold text-white">{app.id}</span>
                                                </div>
                                                <span className="text-[10px] text-zinc-500">from draft: {app.draft_id}</span>
                                            </div>
                                            <div className="text-right text-[10px] text-zinc-500">
                                                <div>{new Date(app.approved_at).toLocaleString()}</div>
                                                {app.approved_by && <div className="text-zinc-600">by {app.approved_by}</div>}
                                            </div>
                                        </div>
                                        <p className="text-[11px] text-zinc-300 mb-3">"{app.prompt}"</p>
                                        <pre className="p-3 bg-black/40 rounded-xl text-[10px] text-zinc-400 max-h-32 overflow-auto font-mono whitespace-pre-wrap mb-3">
                                            {app.content}
                                        </pre>
                                        <div className="flex items-center justify-between">
                                            <span className="text-[9px] text-zinc-600">
                                                {hasRun ? 'Has run(s)' : 'No runs yet'}
                                            </span>
                                            {!hasRun && (
                                                <button
                                                    onClick={() => startRun(app.id)}
                                                    className="px-4 py-1.5 bg-blue-500/20 text-blue-400 rounded-lg text-[9px] font-black uppercase hover:bg-blue-500/30 transition-all flex items-center space-x-1"
                                                >
                                                    <Play className="w-3 h-3" />
                                                    <span>Deploy</span>
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                );
                            })
                        ) : (
                            <div className="h-64 flex flex-col items-center justify-center text-zinc-600">
                                <CheckCircle2 className="w-12 h-12 mb-4 opacity-20" />
                                <p className="text-xs font-black uppercase tracking-widest opacity-40">No approved operations</p>
                            </div>
                        )}
                    </div>
                )}

                {/* ═══ RUNS TAB ═══ */}
                {activeTab === 'runs' && (
                    <div className="space-y-4 animate-fade-in">
                        {runs.length > 0 ? (
                            runs.map(run => (
                                <div key={run.id} className="glass-card overflow-hidden border border-white/5 rounded-2xl bg-[#1c1c1e]">
                                    <div
                                        className="p-4 flex items-center justify-between border-b border-white/5 bg-white/[0.02] cursor-pointer"
                                        onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                                    >
                                        <div className="flex items-center space-x-4">
                                            <div className="flex items-center space-x-2">
                                                <History className="w-4 h-4 text-blue-400" />
                                                <span className="text-xs font-bold text-white">{run.id}</span>
                                            </div>
                                            <span className="text-[10px] text-zinc-500 font-mono">from: {run.approved_id}</span>
                                            {statusBadge(run.status)}
                                        </div>
                                        <div className="flex items-center space-x-3">
                                            {(run.status === 'pending' || run.status === 'running') && (
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); cancelRun(run.id); }}
                                                    className="px-3 py-1 bg-red-500/10 text-red-400 rounded-lg text-[9px] font-black uppercase hover:bg-red-500/20 transition-all flex items-center space-x-1"
                                                >
                                                    <X className="w-3 h-3" />
                                                    <span>Cancel</span>
                                                </button>
                                            )}
                                            {getStatusIcon(run.status)}
                                        </div>
                                    </div>
                                    {(expandedRun === run.id || run.status === 'running') && (
                                        <div className="bg-zinc-950/40 p-4 max-h-64 overflow-y-auto font-mono text-[10px] space-y-1">
                                            {run.log.length > 0 ? (
                                                run.log.map((log, i) => (
                                                    <div key={`${run.id}-${i}`} className="flex space-x-3">
                                                        <span className="text-zinc-700 whitespace-nowrap">[{log.ts.split('T')[1]?.split('.')[0] || log.ts}]</span>
                                                        <span className={log.level === 'ERROR' ? 'text-red-400' : log.level === 'WARN' ? 'text-amber-400' : 'text-zinc-400'}>
                                                            {log.msg}
                                                        </span>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-zinc-700 flex items-center space-x-2">
                                                    <Terminal className="w-3 h-3" />
                                                    <span>Awaiting execution logs...</span>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))
                        ) : (
                            <div className="h-64 flex flex-col items-center justify-center text-zinc-600">
                                <History className="w-12 h-12 mb-4 opacity-20" />
                                <p className="text-xs font-black uppercase tracking-widest opacity-40">No runs recorded</p>
                            </div>
                        )}
                    </div>
                )}

                {/* ═══ CONFIG TAB ═══ */}
                {activeTab === 'config' && (
                    <div className="space-y-6 animate-fade-in">
                        {config ? (
                            <div className="p-6 border border-white/5 rounded-2xl bg-[#1c1c1e]">
                                <div className="flex items-center space-x-3 mb-6 text-zinc-300">
                                    <Settings className="w-5 h-5" />
                                    <span className="text-sm font-black uppercase tracking-widest">Runtime Configuration</span>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <ConfigToggle
                                        label="Default Auto-Run"
                                        description="When enabled, approving a draft will automatically create a run"
                                        value={config.default_auto_run}
                                        onChange={(v) => updateConfig({ ...config, default_auto_run: v })}
                                    />
                                    <ConfigToggle
                                        label="Operator Can Generate"
                                        description="Allow operator tokens to call /ops/generate"
                                        value={config.operator_can_generate}
                                        onChange={(v) => updateConfig({ ...config, operator_can_generate: v })}
                                    />
                                    <ConfigNumber
                                        label="Max Concurrent Runs"
                                        description="Maximum runs processing simultaneously"
                                        value={config.max_concurrent_runs}
                                        min={1} max={10}
                                        onChange={(v) => updateConfig({ ...config, max_concurrent_runs: v })}
                                    />
                                    <ConfigNumber
                                        label="Draft Cleanup TTL (days)"
                                        description="Rejected drafts older than this are cleaned up"
                                        value={config.draft_cleanup_ttl_days}
                                        min={1} max={90}
                                        onChange={(v) => updateConfig({ ...config, draft_cleanup_ttl_days: v })}
                                    />
                                </div>
                            </div>
                        ) : (
                            <div className="h-64 flex flex-col items-center justify-center text-zinc-600">
                                <Settings className="w-12 h-12 mb-4 opacity-20" />
                                <p className="text-xs font-black uppercase tracking-widest opacity-40">Config not available (requires operator+ role)</p>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

/* ── Helper Components ── */

const ConfigToggle: React.FC<{
    label: string; description: string; value: boolean; onChange: (v: boolean) => void;
}> = ({ label, description, value, onChange }) => (
    <div className="p-4 bg-black/20 rounded-xl border border-white/5">
        <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-zinc-200">{label}</span>
            <button
                onClick={() => onChange(!value)}
                className={`w-10 h-5 rounded-full transition-colors relative ${value ? 'bg-emerald-500' : 'bg-zinc-700'}`}
            >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${value ? 'left-5' : 'left-0.5'}`} />
            </button>
        </div>
        <p className="text-[10px] text-zinc-500">{description}</p>
    </div>
);

const ConfigNumber: React.FC<{
    label: string; description: string; value: number; min: number; max: number; onChange: (v: number) => void;
}> = ({ label, description, value, min, max, onChange }) => (
    <div className="p-4 bg-black/20 rounded-xl border border-white/5">
        <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-zinc-200">{label}</span>
            <input
                type="number"
                value={value}
                min={min} max={max}
                onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    if (!isNaN(n) && n >= min && n <= max) onChange(n);
                }}
                className="w-16 bg-black/40 border border-white/10 rounded-lg px-2 py-1 text-xs text-white text-center outline-none focus:border-blue-500/40"
            />
        </div>
        <p className="text-[10px] text-zinc-500">{description}</p>
    </div>
);
