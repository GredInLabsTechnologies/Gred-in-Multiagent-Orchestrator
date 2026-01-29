import React from 'react';
import { Layers, Server, Code, FolderOpen, Settings, Zap } from 'lucide-react';

interface MockSidebarProps {
    activeTab: 'creative' | 'system' | 'json';
    setActiveTab: (tab: 'creative' | 'system' | 'json') => void;
}

export const MockSidebar: React.FC<MockSidebarProps> = ({ activeTab, setActiveTab }) => {
    const pipelines = [
        "ANIMATION FRAME GEN",
        "ANIMATION FRAME GEN API",
        "BASE SPRITE GEN",
        "BASE SPRITE GEN API",
        "BASE SPRITE GEN FLUX API",
        "CHAR SHEET DATASET GEN",
        "SD15 PIXEL SPRITE GEN API",
        "SDXL PIXEL SPRITE GEN API"
    ];

    return (
        <div className="flex-1 flex flex-col p-6 overflow-hidden">
            {/* Logo/Title */}
            <div className="flex items-center space-x-3 mb-8">
                <div className="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center border border-white/5 shadow-xl">
                    <img src="/logo.png" className="w-6 h-6 object-contain" alt="" />
                </div>
                <div>
                    <h1 className="text-xl font-bold tracking-tighter text-white/90 leading-none">GRED <span className="text-accent-primary font-light">IN LABS</span></h1>
                    <p className="text-[10px] text-slate-500 font-bold tracking-[0.2em] mt-1 uppercase">Assets Engine | GIOS</p>
                </div>
            </div>

            {/* Tab Navigation */}
            <div className="flex p-1 bg-black/40 rounded-xl mb-6 border border-white/5">
                <button onClick={() => setActiveTab('creative')} className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-wider flex items-center justify-center space-x-2 transition-all ${activeTab === 'creative' ? 'bg-accent-primary text-white shadow-lg' : 'text-slate-500 hover:text-white'}`}>
                    <Layers className="w-3 h-3" />
                    <span>Creative</span>
                </button>
                <button onClick={() => setActiveTab('system')} className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-wider flex items-center justify-center space-x-2 transition-all ${activeTab === 'system' ? 'bg-accent-primary text-white shadow-lg' : 'text-slate-500 hover:text-white'}`}>
                    <Server className="w-3 h-3" />
                    <span>System</span>
                </button>
                <button onClick={() => setActiveTab('json')} className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-wider flex items-center justify-center space-x-2 transition-all ${activeTab === 'json' ? 'bg-accent-primary text-white shadow-lg' : 'text-slate-500 hover:text-white'}`}>
                    <Code className="w-3 h-3" />
                    <span>Json</span>
                </button>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar space-y-8 pr-2">
                {/* Pipelines */}
                <div className="space-y-4">
                    <div className="flex items-center space-x-2 opacity-50">
                        <Layers className="w-3 h-3 text-slate-400" />
                        <span className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-400">Pipelines</span>
                    </div>
                    <div className="space-y-1">
                        {pipelines.map(p => (
                            <div key={p} className="px-3 py-2 rounded-lg text-[10px] font-bold text-slate-400 hover:bg-white/5 hover:text-white cursor-pointer transition-all uppercase tracking-tight">
                                {p}
                            </div>
                        ))}
                    </div>
                </div>

                {/* Variability (Seed) */}
                <div className="space-y-4">
                    <div className="flex items-center justify-between">
                        <span className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">Variability (Seed)</span>
                        <Zap className="w-3 h-3 text-accent-secondary" />
                    </div>
                    <input type="text" value="-1" readOnly className="w-full bg-black/40 border border-white/5 rounded-xl px-4 py-3 text-xs font-mono text-slate-300 outline-none" />
                </div>

                {/* Advanced Config */}
                <div className="flex items-center justify-between opacity-50">
                    <div className="flex items-center space-x-2">
                        <Code className="w-3 h-3 text-slate-500" />
                        <span className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">Advanced Config</span>
                    </div>
                    <Layers className="w-3 h-3 text-slate-500" />
                </div>
            </div>

            {/* Storage Vault Button */}
            <div className="pt-6">
                <button className="w-full py-4 bg-gradient-to-br from-slate-900 to-black border border-white/10 rounded-2xl flex items-center justify-center space-x-3 group hover:border-accent-primary/40 transition-all shadow-xl">
                    <FolderOpen className="w-4 h-4 text-slate-500 group-hover:text-accent-primary" />
                    <span className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 group-hover:text-white">Storage Vault</span>
                </button>
            </div>

            {/* Footer Admin */}
            <div className="mt-8 pt-4 border-t border-white/5 flex items-center justify-between">
                <div className="flex items-center space-x-3">
                    <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center border border-white/10 overflow-hidden">
                        <span className="text-[10px] font-bold text-white">AD</span>
                    </div>
                    <div>
                        <p className="text-[11px] font-bold text-white">Admin</p>
                        <p className="text-[9px] text-slate-500 font-mono">Ping: 0ms</p>
                    </div>
                </div>
                <Settings className="w-4 h-4 text-slate-600 cursor-pointer hover:text-white transition-colors" />
            </div>
        </div>
    );
};
