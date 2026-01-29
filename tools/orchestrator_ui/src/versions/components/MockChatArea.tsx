import React from 'react';
import { Sparkles } from 'lucide-react';

// Note: isZenMode prop removed as it was unused
export const MockChatArea: React.FC = () => {
    const shortcuts = [
        { icon: "🔥", text: "Fire Dragon" },
        { icon: "⚔️", text: "Mystic Sword" },
        { icon: "🌲", text: "Pixel Forest" },
        { icon: "🏰", text: "Dark Castle" }
    ];

    return (
        <div className="flex-1 flex flex-col items-center justify-center relative p-8">
            {/* AutoTune Badge */}
            <div className="absolute top-4 right-8 flex items-center space-x-2 bg-accent-secondary/10 border border-accent-secondary/20 px-3 py-1.5 rounded-full scale-90">
                <Sparkles className="w-3 h-3 text-accent-secondary animate-pulse" />
                <span className="text-[10px] font-black uppercase tracking-widest text-accent-secondary">Autotune Active</span>
            </div>

            {/* Center Area */}
            <div className="w-full max-w-2xl flex flex-col items-center text-center space-y-8">
                {/* Visual Placeholder */}
                <div className="w-20 h-20 rounded-full bg-white/5 flex items-center justify-center border border-white/5 shadow-2xl relative overflow-hidden group">
                    <div className="absolute inset-0 bg-accent-primary/10 blur-xl opacity-0 group-hover:opacity-100 transition-opacity" />
                    <Sparkles className="w-8 h-8 text-white/20 group-hover:text-accent-primary transition-colors" />
                </div>

                <div className="space-y-2">
                    <h2 className="text-3xl font-black tracking-tighter text-white/90">LABS ORCHESTRATOR</h2>
                    <p className="text-sm text-slate-500 max-w-md mx-auto leading-relaxed">
                        Your gateway to industrial-grade asset generation. Start with a prompt or use a shortcut below.
                    </p>
                </div>

                {/* Shortcuts */}
                <div className="flex flex-wrap justify-center gap-3">
                    {shortcuts.map(s => (
                        <button key={s.text} className="bg-white/5 hover:bg-white/10 border border-white/5 px-4 py-2 rounded-full flex items-center space-x-2 transition-all">
                            <span className="text-xs">{s.icon}</span>
                            <span className="text-[10px] font-bold text-slate-300 uppercase tracking-tight">{s.text}</span>
                        </button>
                    ))}
                </div>

                {/* Main Input */}
                <div className="w-full mt-12 relative group">
                    <div className="absolute inset-0 bg-accent-primary/20 blur-3xl opacity-0 group-focus-within:opacity-100 transition-opacity duration-1000" />
                    <div className="relative flex items-center bg-slate-900/80 backdrop-blur-2xl border border-white/10 rounded-[2.5rem] p-2 pl-8 focus-within:border-accent-primary/50 transition-all shadow-2xl overflow-hidden">
                        <input
                            type="text"
                            placeholder="What do you want to create?"
                            className="flex-1 bg-transparent py-4 text-sm text-white placeholder-slate-500 outline-none"
                            readOnly
                        />
                        <button className="bg-accent-primary hover:bg-accent-primary/90 text-[10px] font-black uppercase tracking-[0.2em] text-white px-8 py-4 rounded-[2rem] flex items-center space-x-2 shadow-lg transition-transform active:scale-95">
                            <span>Launch</span>
                        </button>
                    </div>
                </div>

                <p className="text-[9px] text-slate-600 font-bold uppercase tracking-[0.3em] mt-8">Gred Labs GIOS V2.0 | Industrial Generation</p>
            </div>
        </div>
    );
};
