import React from 'react';
import { Image as ImageIcon, FileJson, FolderOpen, Download, CheckCircle2, Clock } from 'lucide-react';
import { TheVault } from '../components/TheVault';
import { API_BASE, Message } from '../types';

interface OutputIslandProps {
    rightTab: 'output' | 'runs';
    setRightTab: (tab: 'output' | 'runs') => void;
    history: string[];
    messages: Message[];
    setMessages: (msgs: Message[] | ((prev: Message[]) => Message[])) => void;
    isVaultOpen: boolean;
    setIsVaultOpen: (open: boolean) => void;
    handleAnalyze: (path: string) => void;
    isAnalyzing: boolean;
}

export const OutputIsland: React.FC<OutputIslandProps> = ({
    rightTab,
    setRightTab,
    history,
    isVaultOpen,
    setIsVaultOpen,
    handleAnalyze,
    isAnalyzing
}) => {
    const activeImage = history.length > 0 ? `${API_BASE}/outputs/${history[0]}` : null;
    const activeFilename = activeImage?.split('/').pop();
    const activeAssetId = activeFilename?.replace('.png', '').replace('.jpg', '').replace('.pdf', '');

    return (
        <aside className="h-full glass-panel rounded-[2.5rem] flex flex-col p-8 space-y-8 border border-white/10 shadow-2xl bg-black/20 sidebar-transition relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-b from-accent-primary/5 to-transparent pointer-events-none" />

            {/* Tabs */}
            <div className="flex bg-black/60 p-1.5 rounded-2xl border border-white/5 shrink-0 relative z-10">
                <button
                    onClick={() => setRightTab('output')}
                    className={`flex-1 flex items-center justify-center space-x-2 py-3 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${rightTab === 'output' ? 'bg-accent-primary text-white shadow-[0_0_20px_rgba(124,58,237,0.3)]' : 'text-slate-500 hover:text-white hover:bg-white/5'}`}
                >
                    <span>Current</span>
                </button>
                <button
                    onClick={() => setRightTab('runs')}
                    className={`flex-1 flex items-center justify-center space-x-2 py-3 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${rightTab === 'runs' ? 'bg-accent-primary text-white shadow-[0_0_20px_rgba(124,58,237,0.3)]' : 'text-slate-500 hover:text-white hover:bg-white/5'}`}
                >
                    <span>History</span>
                </button>
            </div>

            {rightTab === 'output' ? (
                <div className="flex-1 flex flex-col space-y-6 overflow-hidden animate-fade-in relative z-10">
                    {/* Preview Area */}
                    <div className="aspect-square rounded-3xl flex flex-col items-center justify-center bg-black/60 border border-white/10 relative overflow-hidden group shadow-2xl">
                        {activeImage ? (
                            <>
                                <img
                                    src={activeImage}
                                    alt="Asset Preview"
                                    className="w-full h-full object-contain p-6 drop-shadow-[0_0_30px_rgba(0,0,0,0.5)] transition-transform duration-700 group-hover:scale-105"
                                />

                                <div className="absolute inset-x-4 bottom-4 bg-black/60 opacity-0 group-hover:opacity-100 translate-y-4 group-hover:translate-y-0 transition-all duration-300 flex flex-col p-4 space-y-2 backdrop-blur-xl rounded-2xl border border-white/10">
                                    <button
                                        onClick={() => activeFilename && handleAnalyze(activeFilename)}
                                        disabled={isAnalyzing}
                                        className="w-full py-3 rounded-xl bg-accent-primary hover:bg-purple-600 text-[10px] font-black uppercase tracking-widest text-white transition-all disabled:opacity-50"
                                    >
                                        {isAnalyzing ? "Processing QA..." : "Run Quality Audit"}
                                    </button>
                                </div>
                            </>
                        ) : (
                            <div className="flex flex-col items-center justify-center text-slate-700">
                                <ImageIcon className="w-16 h-16 mb-4 opacity-20 animate-pulse" />
                                <p className="text-[11px] uppercase tracking-[0.3em] font-black opacity-30">Waiting for Output</p>
                            </div>
                        )}
                    </div>

                    {/* Metadata Card */}
                    {activeAssetId && (
                        <div className="p-6 bg-white/5 rounded-3xl border border-white/5 space-y-4 shadow-inner">
                            <div className="flex items-center justify-between">
                                <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Asset Profile</h3>
                                <span className="text-[10px] font-mono text-slate-500 bg-black/40 px-2 py-0.5 rounded italic">#{activeAssetId.slice(0, 8)}</span>
                            </div>

                            <div className="grid grid-cols-2 gap-3">
                                <div className="p-3 bg-black/20 rounded-xl border border-white/5">
                                    <p className="text-[8px] text-slate-600 uppercase font-black tracking-widest mb-1">Architecture</p>
                                    <p className="text-[11px] text-slate-200 font-bold tracking-tight">System Core</p>
                                </div>
                                <div className="p-3 bg-black/20 rounded-xl border border-white/5">
                                    <p className="text-[8px] text-slate-600 uppercase font-black tracking-widest mb-1">Validation</p>
                                    <div className="flex items-center space-x-1.5">
                                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                                        <p className="text-[11px] text-emerald-400 font-bold uppercase tracking-widest">Verified</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Actions */}
                    <div className="grid grid-cols-3 gap-3 pt-2">
                        {[
                            { icon: Download, label: "Export" },
                            { icon: FolderOpen, label: "Locate" },
                            { icon: FileJson, label: "Schema" }
                        ].map((action, i) => (
                            <button key={i} className="flex flex-col items-center justify-center p-4 bg-white/5 hover:bg-white/10 rounded-2xl border border-white/5 transition-all group active:scale-95">
                                <action.icon className="w-5 h-5 text-slate-500 group-hover:text-accent-secondary mb-2 transition-colors" />
                                <span className="text-[9px] font-black text-slate-600 uppercase tracking-widest group-hover:text-slate-300">{action.label}</span>
                            </button>
                        ))}
                    </div>
                </div>
            ) : (
                <div className="flex-1 flex flex-col space-y-6 overflow-hidden animate-fade-in relative z-10">
                    <div className="flex items-center justify-between px-2">
                        <h2 className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">History Log</h2>
                        <span className="text-[10px] font-mono text-accent-primary bg-accent-primary/10 px-2 py-0.5 rounded-full">{history.length} Assets</span>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
                        {history.map((filename, i) => (
                            <div
                                key={i}
                                onClick={() => {
                                    setRightTab('output');
                                }}
                                className="p-3 rounded-2xl bg-white/5 border border-white/5 hover:border-accent-primary/30 hover:bg-accent-primary/5 transition-all cursor-pointer group flex items-center space-x-4 glass-card"
                            >
                                <div className="w-14 h-14 rounded-xl bg-black/60 border border-white/10 overflow-hidden p-1.5 flex-shrink-0 group-hover:scale-110 transition-transform">
                                    <img src={`${API_BASE}/outputs/${filename}`} alt="Thumb" className="w-full h-full object-contain" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-[11px] font-bold text-slate-100 truncate tracking-tight">{filename.replace('.png', '').replace('.jpg', '').toUpperCase()}</span>
                                    </div>
                                    <div className="flex items-center space-x-3 text-[9px] text-slate-500 font-black uppercase tracking-widest">
                                        <span className="text-accent-primary">CORE</span>
                                        <span className="flex items-center opacity-40"><Clock className="w-2.5 h-2.5 mr-1" /> ACTIVE</span>
                                    </div>
                                </div>
                                <CheckCircle2 className="w-4 h-4 text-emerald-500 opacity-20 group-hover:opacity-100 transition-opacity" />
                            </div>
                        ))}
                        {history.length === 0 && (
                            <div className="flex-1 flex flex-col items-center justify-center pt-20 text-slate-700">
                                <Clock className="w-12 h-12 mb-4 opacity-10" />
                                <p className="text-[10px] font-black uppercase tracking-widest opacity-20">No history available</p>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {isVaultOpen && (
                <TheVault
                    assets={history}
                    apiBase={API_BASE}
                    onClose={() => setIsVaultOpen(false)}
                    onSelectAsset={() => {
                        setIsVaultOpen(false);
                        setRightTab('output');
                    }}
                />
            )}
        </aside>
    );
};

