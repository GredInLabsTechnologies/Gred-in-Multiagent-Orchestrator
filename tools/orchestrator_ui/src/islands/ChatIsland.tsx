/*
ISLAND: Chat Island
ROLE: Handles the conversational UI and message orchestration.
CONTEXT: Entry point for user intent. Communicates with /chat and triggers generation actions.
DEPENDENCIES: Message, API_BASE
ROLLBACK: Restore logic to App.tsx
LAST_MODIFIED: 2026-01-20
*/

import React from 'react';
import { X, Sparkles, BrainCircuit } from 'lucide-react';
import { Message, IslandProgress } from '../types';

interface ChatIslandProps {
    messages: Message[];
    input: string;
    setInput: (val: string | ((prev: string) => string)) => void;
    handleSend: () => void;
    isProcessing: boolean;
    chatEndRef: React.RefObject<HTMLDivElement>;
    latentPreview: string | null;
    genProgress: number;
    genStatus: string;
    islandProgress: IslandProgress | null;
    activePromptId: string | null;
    isZenMode: boolean;
    isAgentThinking?: boolean;
    isAutoTuneEnabled?: boolean;
}

const IntentChips = ({ setInput }: { setInput: (v: string) => void }) => {
    const intents = [
        { label: "🔥 Fire Dragon", prompt: "A fierce fire dragon, red scales, cinematic lighting, 8k" },
        { label: "⚔️ Mystic Sword", prompt: "A legendary mystic sword, glowing runes, dark steel" },
        { label: "🌲 Pixel Forest", prompt: "A dense pixel art forest tile, 16-bit style, vibrant greens" },
        { label: "🏰 Dark Castle", prompt: "A gothic dark castle, lightning in background, silhouette" }
    ];

    return (
        <div className="flex flex-wrap gap-2 mb-4 animate-slide-up">
            {intents.map((intent, idx) => (
                <button
                    key={idx}
                    onClick={() => setInput(intent.prompt)}
                    className="px-4 py-2 bg-white/5 hover:bg-accent-primary/20 border border-white/5 hover:border-accent-primary/30 rounded-full text-[11px] font-bold text-slate-400 hover:text-white transition-all hover:scale-105 active:scale-95"
                >
                    {intent.label}
                </button>
            ))}
        </div>
    );
};

export const ChatIsland: React.FC<ChatIslandProps> = ({
    messages,
    input,
    setInput,
    handleSend,
    isProcessing,
    chatEndRef,
    latentPreview,
    genProgress,
    genStatus,
    islandProgress,
    activePromptId,
    isZenMode,
    isAgentThinking = false,
    isAutoTuneEnabled = false
}) => {
    return (
        <main className={`flex-1 flex flex-col relative sidebar-transition ${isZenMode ? 'mx-20' : ''}`}>

            {/* Agent Thinking Overlay */}
            {isAgentThinking && (
                <div className="absolute top-12 left-1/2 -translate-x-1/2 z-[60] animate-fade-in pointer-events-none">
                    <div className="flex items-center space-x-3 px-6 py-3 bg-accent-primary/10 backdrop-blur-3xl border border-accent-primary/20 rounded-full shadow-[0_0_50px_rgba(124,58,237,0.2)]">
                        <div className="relative">
                            <BrainCircuit className="w-5 h-5 text-accent-primary animate-pulse" />
                            <div className="absolute inset-0 bg-accent-primary blur-md opacity-50 animate-pulse" />
                        </div>
                        <div className="flex flex-col">
                            <span className="text-[10px] font-black text-accent-primary uppercase tracking-[0.2em]">Agent is Analyzing</span>
                            <span className="text-[9px] text-slate-400 font-medium">Neural heuristics active...</span>
                        </div>
                    </div>
                </div>
            )}

            {/* AutoTune Status Badge */}
            <div className="absolute top-6 right-12 z-50">
                <div className={`flex items-center space-x-2 px-3 py-1.5 rounded-full border transition-all ${isAutoTuneEnabled ? 'bg-accent-secondary/10 border-accent-secondary/20 text-accent-secondary' : 'bg-white/5 border-white/5 text-slate-500 opacity-50'}`}>
                    <Sparkles className={`w-3 h-3 ${isAutoTuneEnabled ? 'animate-pulse' : ''}`} />
                    <span className="text-[9px] font-black uppercase tracking-widest">{isAutoTuneEnabled ? 'AutoTune Active' : 'AutoTune Off'}</span>
                </div>
            </div>

            {/* Chat History */}
            <div className="flex-1 overflow-y-auto p-12 space-y-8 custom-scrollbar">
                {messages.length === 0 && (
                    <div className="h-full flex flex-col items-center justify-center text-center space-y-6 animate-fade-in">
                        <div className="w-20 h-20 bg-accent-primary/10 rounded-full flex items-center justify-center border border-accent-primary/20 shadow-[0_0_30px_rgba(124,58,237,0.1)]">
                            <img src="/logo.png" alt="GRED" className="w-12 h-12 grayscale opacity-50" />
                        </div>
                        <div className="max-w-md">
                            <h2 className="text-2xl font-black tracking-tighter text-white/80">LABS ORCHESTRATOR</h2>
                            <p className="text-sm text-slate-500 mt-2 font-medium tracking-tight">Your gateway to industrial-grade asset generation. Start with a prompt or use a shortcut below.</p>
                        </div>
                    </div>
                )}

                {messages.map((m) => (
                    <div key={m.id} className={`flex ${m.type === 'user' ? 'justify-end' : 'justify-start'} animate-slide-up`}>
                        <div className={`max-w-[80%] p-6 rounded-3xl ${m.type === 'ai' ? 'chat-bubble-ai' : 'chat-bubble-user'} shadow-2xl backdrop-blur-md relative overflow-hidden`}>
                            {m.type === 'ai' && isAutoTuneEnabled && (
                                <div className="absolute top-0 right-0 p-2 opacity-20">
                                    <Sparkles className="w-4 h-4" />
                                </div>
                            )}
                            <p className="text-[15px] leading-relaxed font-medium text-slate-100">{m.text}</p>

                            {m.text.includes("Rendering Asset") && (activePromptId === null || m.text.includes(activePromptId)) && (
                                <div className="mt-4 space-y-4">
                                    {latentPreview && (
                                        <div className="relative aspect-square w-full max-w-[400px] rounded-2xl overflow-hidden border border-white/10 bg-black/40 group shadow-2xl">
                                            <img
                                                src={latentPreview}
                                                alt="Latent Preview"
                                                className="w-full h-full object-contain p-4 animate-pulse-subtle"
                                            />
                                            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />
                                            <div className="absolute bottom-4 left-4 right-4 flex justify-between items-end">
                                                <div className="flex flex-col">
                                                    <span className="text-[10px] font-black text-accent-secondary uppercase tracking-[0.2em] mb-1">Pixel Stream</span>
                                                    <span className="text-[10px] font-mono text-white/50">{genStatus || 'Processing...'}</span>
                                                </div>
                                                <span className="text-2xl font-black text-white italic tracking-tighter">{genProgress}%</span>
                                            </div>
                                        </div>
                                    )}
                                    <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden border border-white/5">
                                        <div
                                            className="h-full bg-gradient-to-r from-accent-primary to-accent-secondary transition-all duration-500 rounded-full shadow-[0_0_15px_rgba(124,58,237,0.4)]"
                                            style={{ width: `${genProgress || 5}%` }}
                                        />
                                    </div>
                                    {islandProgress && (
                                        <div className="flex items-center space-x-2">
                                            <div className="w-1.5 h-1.5 rounded-full bg-accent-secondary animate-ping" />
                                            <span className="text-[10px] font-black text-accent-secondary uppercase tracking-widest">
                                                Active Island: {islandProgress.island}
                                            </span>
                                        </div>
                                    )}
                                </div>
                            )}

                            {m.evolutionSuggestions && (
                                <div className="mt-6 flex flex-wrap gap-2 animate-fade-in border-t border-white/5 pt-4">
                                    <p className="w-full text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1">Refine Asset</p>
                                    {m.evolutionSuggestions.map((s, idx) => (
                                        <button
                                            key={idx}
                                            onClick={() => setInput(`Evolve this sprite with a ${s}`)}
                                            className="px-4 py-2 bg-accent-secondary/5 hover:bg-accent-secondary/20 border border-accent-secondary/20 rounded-xl text-[11px] text-accent-secondary transition-all font-bold hover:scale-105"
                                        >
                                            + {s.toUpperCase()}
                                        </button>
                                    ))}
                                </div>
                            )}

                            <p className="text-[10px] mt-4 opacity-20 font-mono italic tracking-tight">
                                {m.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </p>
                        </div>
                    </div>
                ))}
                <div ref={chatEndRef} />
            </div>

            {/* Input Area */}
            <div className={`py-12 px-12 pt-0 transition-all duration-500 ${isZenMode ? 'max-w-4xl mx-auto w-full' : ''}`}>
                {messages.length === 0 && <IntentChips setInput={setInput} />}

                <div className="relative group">
                    <div className="absolute -inset-1 bg-gradient-to-r from-accent-primary to-accent-secondary rounded-[2.5rem] opacity-20 group-hover:opacity-30 blur-xl transition duration-500" />
                    <div className="relative flex items-center space-x-3 p-4 glass-panel rounded-[2.5rem] shadow-2xl border border-white/10 backdrop-blur-3xl bg-black/40">
                        <input
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                            placeholder="What do you want to create?"
                            className="flex-1 bg-transparent border-none outline-none px-6 py-2 text-slate-100 placeholder-slate-500 font-medium text-base tracking-tight"
                        />
                        {input && (
                            <button
                                onClick={() => setInput('')}
                                className="p-2 text-slate-500 hover:text-white transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        )}
                        <button
                            onClick={handleSend}
                            disabled={isProcessing || isAgentThinking}
                            className={`px-10 py-4 rounded-[1.8rem] text-white font-black transition-all shadow-2xl ${isProcessing || isAgentThinking ? 'bg-slate-800 opacity-50 cursor-wait' : 'bg-gradient-to-r from-accent-primary to-purple-600 hover:scale-[1.02] active:scale-95 shadow-accent-primary/20'}`}
                        >
                            <span className="tracking-[0.15em] text-[11px] uppercase italic">
                                {isProcessing ? 'Thinking...' : isAgentThinking ? 'Observing...' : 'Launch'}
                            </span>
                        </button>
                    </div>
                </div>
                <p className="text-center text-[9px] text-slate-600 font-bold uppercase tracking-[0.3em] mt-6 pointer-events-none">
                    GRED LABS GIOS v2.0 | INDUSTRIAL GENERATION
                </p>
            </div>
        </main>
    );
};
