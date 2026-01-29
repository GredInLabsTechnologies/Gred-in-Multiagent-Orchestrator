/*
ISLAND: AIAssistantPanel
ROLE: Right panel combining chat functionality with output gallery
CONTEXT: Replaces both ChatIsland and OutputIsland. Contains AI messages, variations carousel, and user input.
LAST_MODIFIED: 2026-01-21
*/

import React, { useRef, useEffect } from 'react';
import { Send, Mic, Sparkles, BrainCircuit } from 'lucide-react';
import { Message } from '../types';

interface AIAssistantPanelProps {
    messages: Message[];
    input: string;
    setInput: (val: string | ((prev: string) => string)) => void;
    handleSend: () => void;
    isProcessing: boolean;
    isAgentThinking?: boolean;
}

export const AIAssistantPanel: React.FC<AIAssistantPanelProps> = ({
    messages,
    input,
    setInput,
    handleSend,
    isProcessing,
    isAgentThinking = false
}) => {
    const chatEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom on new messages
    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    return (
        <aside className="h-full flex flex-col bg-white/[0.02] border border-white/5 rounded-2xl overflow-hidden">
            {/* Header */}
            <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
                <h2 className="text-sm font-black uppercase tracking-[0.15em] text-slate-300">AI Assistant</h2>
                {isAgentThinking && (
                    <div className="flex items-center space-x-2 text-accent-primary">
                        <BrainCircuit className="w-4 h-4 animate-pulse" />
                        <span className="text-[9px] font-bold uppercase tracking-wider">Thinking...</span>
                    </div>
                )}
            </div>

            {/* Chat Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
                {messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center space-y-4 opacity-50">
                        <Sparkles className="w-8 h-8 text-accent-primary" />
                        <p className="text-xs text-slate-500">Ask me to analyze the repo, find files, or plan changes...</p>
                    </div>
                ) : (
                    messages.map((m) => (
                        <div
                            key={m.id}
                            className={`flex ${m.type === 'user' ? 'justify-end' : 'justify-start'} animate-slide-up`}
                        >
                            <div
                                className={`
                                    max-w-[90%] px-4 py-3 rounded-2xl text-sm
                                    ${m.type === 'ai'
                                        ? 'bg-accent-primary/10 border border-accent-primary/20 text-slate-200'
                                        : 'bg-white/5 border border-white/10 text-slate-300'
                                    }
                                `}
                            >
                                {m.type === 'ai' && (
                                    <p className="text-[9px] font-bold text-accent-primary uppercase tracking-wider mb-1">AI Assistant</p>
                                )}
                                {m.type === 'user' && (
                                    <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">You</p>
                                )}
                                <p className="leading-relaxed">{m.text}</p>
                                <p className="text-[9px] mt-2 text-slate-600 italic">
                                    {m.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </p>
                            </div>
                        </div>
                    ))
                )}
                <div ref={chatEndRef} />
            </div>

            <div className="p-4 border-t border-white/5">
                <div className="flex items-center space-x-2 p-2 bg-black/40 border border-white/10 rounded-2xl">
                    <input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                        placeholder="Message AI..."
                        disabled={isProcessing || isAgentThinking}
                        className="flex-1 bg-transparent border-none outline-none px-3 py-2 text-sm text-slate-200 placeholder-slate-600 disabled:opacity-50"
                    />
                    <button
                        className="p-2 text-slate-500 hover:text-white transition-colors"
                        title="Voice input (coming soon)"
                    >
                        <Mic className="w-4 h-4" />
                    </button>
                    <button
                        onClick={handleSend}
                        disabled={isProcessing || isAgentThinking || !input.trim()}
                        className={`
                            p-2.5 rounded-xl transition-all
                            ${isProcessing || isAgentThinking || !input.trim()
                                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                                : 'bg-accent-primary text-white hover:bg-purple-600 active:scale-95'
                            }
                        `}
                    >
                        <Send className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </aside>
    );
};

