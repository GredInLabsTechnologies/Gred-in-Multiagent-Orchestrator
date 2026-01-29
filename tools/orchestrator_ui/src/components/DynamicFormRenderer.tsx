import React from 'react';
import { WorkflowSchema } from '../types';

interface Props {
    schema: WorkflowSchema | null;
    overrides: Record<string, unknown>;
    onChange: (id: string, value: unknown) => void;
}

export const DynamicFormRenderer: React.FC<Props> = ({ schema, overrides, onChange }) => {
    if (!schema) return <div className="text-slate-500 text-[10px] p-4 text-center">Loading workflow geometry...</div>;

    return (
        <div className="space-y-6 animate-fade-in">
            {schema.groups.map((group, gIdx) => (
                <div key={gIdx} className="space-y-3">
                    <div className="px-4 text-[9px] font-black text-slate-500 uppercase tracking-widest flex items-center">
                        <span className="mr-2 h-px bg-white/5 flex-1"></span>
                        {group.name}
                        <span className="ml-2 h-px bg-white/5 flex-1"></span>
                    </div>

                    <div className="space-y-2 px-2">
                        {group.fields.map((field) => {
                            const currentValue = overrides[field.id] !== undefined ? overrides[field.id] : field.default;

                            return (
                                <div key={field.id} className="bg-black/20 p-3 rounded-xl border border-white/5 hover:border-white/10 transition-colors group">
                                    <div className="flex justify-between mb-2">
                                        <label className="text-slate-400 text-[10px] font-medium group-hover:text-slate-200 transition-colors">
                                            {field.label.split(' -> ')[1].toUpperCase()}
                                        </label>
                                        <span className="text-accent-primary font-mono text-[10px]">{String(currentValue)}</span>
                                    </div>

                                    {field.type === 'enum' ? (
                                        <select
                                            value={String(currentValue ?? '')}
                                            onChange={(e) => onChange(field.id, e.target.value)}
                                            className="w-full bg-[#1a1b26] border border-white/10 text-slate-300 text-[10px] py-1 px-2 rounded outline-none focus:border-accent-primary transition-colors appearance-none"
                                        >
                                            {field.constraints?.options?.map(opt => (
                                                <option key={opt} value={opt}>{opt}</option>
                                            ))}
                                        </select>
                                    ) : field.type === 'boolean' ? (
                                        <button
                                            onClick={() => onChange(field.id, !currentValue)}
                                            className={`w-full py-1 px-4 rounded-lg text-[10px] font-bold border transition-all ${currentValue ? 'bg-accent-primary/20 border-accent-primary text-accent-primary' : 'bg-white/5 border-white/10 text-slate-500'}`}
                                        >
                                            {currentValue ? 'ENABLED' : 'DISABLED'}
                                        </button>
                                    ) : field.type === 'number' ? (
                                        <div className="space-y-1">
                                            <input
                                                type={field.constraints?.max && field.constraints.max > 0 ? "range" : "number"}
                                                min={field.constraints?.min}
                                                max={field.constraints?.max}
                                                step={field.constraints?.step}
                                                value={Number(currentValue ?? 0)}
                                                onChange={(e) => onChange(field.id, parseFloat(e.target.value))}
                                                className="w-full bg-transparent accent-accent-primary h-1.5"
                                            />
                                            <div className="flex justify-between text-[8px] text-slate-600 font-mono">
                                                <span>{field.constraints?.min ?? 'min'}</span>
                                                <span>{field.constraints?.max ?? 'max'}</span>
                                            </div>
                                        </div>
                                    ) : (
                                        <input
                                            type="text"
                                            value={String(currentValue ?? '')}
                                            onChange={(e) => onChange(field.id, e.target.value)}
                                            className="w-full bg-transparent border-b border-white/5 text-slate-300 text-xs py-1 focus:border-accent-primary outline-none transition-colors"
                                        />
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}
        </div>
    );
};
