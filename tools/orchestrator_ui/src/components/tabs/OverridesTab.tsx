import React, { useState, useEffect } from 'react';
import { Terminal, Save, AlertTriangle } from 'lucide-react';

interface OverridesTabProps {
    overrides: Record<string, unknown>;
    setOverrides: React.Dispatch<React.SetStateAction<Record<string, unknown>>>;
}

export const OverridesTab: React.FC<OverridesTabProps> = ({ overrides, setOverrides }) => {
    const [jsonText, setJsonText] = useState(JSON.stringify(overrides, null, 2));
    const [error, setError] = useState<string | null>(null);

    // Sync text when overrides come from outside (e.g. Preset change)
    useEffect(() => {
        setJsonText(JSON.stringify(overrides, null, 2));
    }, [overrides]);

    const handleSave = () => {
        try {
            const parsed = JSON.parse(jsonText);
            setOverrides(parsed);
            setError(null);
        } catch (e) {
            setError((e as Error).message);
        }
    };

    return (
        <div className="px-2 space-y-4 h-full flex flex-col">
            <div className="bg-amber-500/10 border border-amber-500/20 p-3 rounded-lg flex items-start space-x-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <p className="text-[10px] text-amber-200/80 leading-relaxed">
                    <span className="font-bold text-amber-400">WARNING:</span> Modifying raw overrides bypasses UI validation. Incorrect keys may cause engine failures.
                </p>
            </div>

            <div className="flex-1 bg-black/40 border border-white/5 rounded-xl overflow-hidden flex flex-col relative group">
                <div className="bg-white/5 px-4 py-2 flex items-center justify-between border-b border-white/5">
                    <div className="flex items-center space-x-2">
                        <Terminal className="w-3 h-3 text-slate-500" />
                        <span className="text-[10px] font-mono text-slate-500 uppercase">overrides.json</span>
                    </div>
                    {error && <span className="text-[9px] text-red-400 font-bold bg-red-500/10 px-2 py-0.5 rounded">{error}</span>}
                </div>

                <textarea
                    value={jsonText}
                    onChange={(e) => setJsonText(e.target.value)}
                    className="flex-1 w-full bg-transparent p-4 font-mono text-[10px] text-emerald-400/80 resize-none outline-none focus:bg-white/5 transition-colors custom-scrollbar"
                    spellCheck={false}
                />

                <button
                    onClick={handleSave}
                    className="absolute bottom-4 right-4 bg-accent-primary hover:bg-accent-primary/80 text-white p-2 rounded-lg shadow-lg opacity-0 group-hover:opacity-100 transition-all transform translate-y-2 group-hover:translate-y-0"
                    title="Apply Overrides"
                >
                    <Save className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
};
