import React, { useState } from 'react';
import { Download, FolderOpen, Code, Image as ImageIcon } from 'lucide-react';

export const MockOutputPanel: React.FC = () => {
    const [tab, setTab] = useState<'current' | 'history'>('current');

    return (
        <div className="flex-1 flex flex-col p-6 overflow-hidden">
            {/* Navigation */}
            <div className="flex p-1 bg-black/40 rounded-xl mb-8 border border-white/5">
                <button onClick={() => setTab('current')} className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-widest transition-all ${tab === 'current' ? 'bg-accent-primary text-white shadow-lg' : 'text-slate-500 hover:text-white'}`}>
                    Current
                </button>
                <button onClick={() => setTab('history')} className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-widest transition-all ${tab === 'history' ? 'bg-accent-primary text-white shadow-lg' : 'text-slate-500 hover:text-white'}`}>
                    History
                </button>
            </div>

            {/* Main Preview Container */}
            <div className="flex-1 flex flex-col items-center justify-center space-y-8">
                <div className="w-full aspect-square bg-black/60 border border-white/5 rounded-[2.5rem] flex flex-col items-center justify-center space-y-4 shadow-2xl relative overflow-hidden group">
                    <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                    <div className="w-20 h-20 rounded-2xl bg-white/5 flex items-center justify-center border border-white/5">
                        <ImageIcon className="w-8 h-8 text-white/5" />
                    </div>
                    <span className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-700">Waiting for Output</span>
                </div>

                {/* Actions Grid */}
                <div className="grid grid-cols-3 gap-3 w-full">
                    <button className="flex flex-col items-center justify-center p-4 rounded-[1.5rem] bg-white/5 border border-white/5 hover:bg-white/10 hover:border-accent-primary/30 transition-all space-y-2 group opacity-50 cursor-not-allowed">
                        <Download className="w-4 h-4 text-slate-500 group-hover:text-accent-primary" />
                        <span className="text-[8px] font-black uppercase tracking-widest text-slate-500 group-hover:text-white">Export</span>
                    </button>
                    <button className="flex flex-col items-center justify-center p-4 rounded-[1.5rem] bg-white/5 border border-white/5 hover:bg-white/10 hover:border-accent-primary/30 transition-all space-y-2 group opacity-50 cursor-not-allowed">
                        <FolderOpen className="w-4 h-4 text-slate-500 group-hover:text-accent-primary" />
                        <span className="text-[8px] font-black uppercase tracking-widest text-slate-500 group-hover:text-white">Locate</span>
                    </button>
                    <button className="flex flex-col items-center justify-center p-4 rounded-[1.5rem] bg-white/5 border border-white/5 hover:bg-white/10 hover:border-accent-primary/30 transition-all space-y-2 group opacity-50 cursor-not-allowed">
                        <Code className="w-4 h-4 text-slate-500 group-hover:text-accent-primary" />
                        <span className="text-[8px] font-black uppercase tracking-widest text-slate-500 group-hover:text-white">Schema</span>
                    </button>
                </div>
            </div>

            {/* History Placeholder */}
            {tab === 'history' && (
                <div className="mt-8 grid grid-cols-4 gap-2">
                    {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
                        <div key={i} className="aspect-square bg-white/5 border border-white/5 rounded-lg animate-pulse" />
                    ))}
                </div>
            )}
        </div>
    );
};
