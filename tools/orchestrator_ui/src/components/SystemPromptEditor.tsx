import React, { useState } from 'react';
import { Save, Info, Terminal } from 'lucide-react';

interface SystemPromptEditorProps {
    initialPrompt: string;
    onSave: (newPrompt: string) => void;
}

export const SystemPromptEditor: React.FC<SystemPromptEditorProps> = ({
    initialPrompt,
    onSave
}) => {
    const [prompt, setPrompt] = useState(initialPrompt);
    const [isDirty, setIsDirty] = useState(false);

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setPrompt(e.target.value);
        setIsDirty(e.target.value !== initialPrompt);
    };

    return (
        <div className="flex flex-col h-full space-y-4 animate-fade-in">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-white/60">
                    <Terminal size={14} />
                    <span className="text-[10px] font-bold uppercase tracking-widest text-[#0a84ff]">System Brain</span>
                </div>
                <div className="flex gap-2">

                    <button
                        onClick={() => {
                            setPrompt(initialPrompt);
                            setIsDirty(false);
                        }}
                        disabled={!isDirty}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all
                            ${isDirty
                                ? 'bg-white/5 text-[#86868b] hover:bg-white/10'
                                : 'bg-white/5 text-white/5 cursor-not-allowed'}`}
                    >
                        RESTAURAR
                    </button>
                    <button
                        onClick={() => {
                            onSave(prompt);
                            setIsDirty(false);
                        }}
                        disabled={!isDirty}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all
                            ${isDirty
                                ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20 hover:bg-blue-500'
                                : 'bg-white/5 text-white/20 cursor-not-allowed'}`}
                    >
                        <Save size={12} />
                        GUARDAR
                    </button>
                </div>
            </div>

            <div className="relative flex-1 group">
                <textarea
                    value={prompt}
                    onChange={handleChange}
                    className="w-full h-full bg-black/40 border border-white/10 rounded-xl p-4 text-xs font-mono text-blue-100/90 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 resize-none custom-scrollbar leading-relaxed"
                    placeholder="Enter agent system instructions..."
                />
                {!isDirty && (
                    <div className="absolute top-4 right-4 text-[10px] font-bold text-emerald-500/60 flex items-center gap-1 select-none pointer-events-none">
                        <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                        SYNCED WITH PLAN
                    </div>
                )}
            </div>

            <div className="p-3 bg-blue-500/5 border border-blue-500/10 rounded-xl flex gap-3">
                <div className="mt-0.5">
                    <Info size={14} className="text-blue-400" />
                </div>
                <p className="text-[10px] text-blue-200/60 leading-relaxed">
                    Changes made here will modify the agent's behavior for this specific task.
                    GIMO ensures all changes are logged for transparency and security.
                </p>
            </div>

            <div className="flex justify-between items-center text-[10px] text-white/20 font-mono px-1">
                <span>{prompt.length} chars</span>
                <span>{Math.ceil(prompt.length / 4)} tokens (approx)</span>
            </div>
        </div>
    );
};
