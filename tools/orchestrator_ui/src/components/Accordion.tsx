/*
COMPONENT: Accordion
ROLE: Collapsible section for ControlIsland panels
CONTEXT: Used in Generation Settings, Creative Tools, etc.
LAST_MODIFIED: 2026-01-21
*/

import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

interface AccordionProps {
    title: string;
    defaultOpen?: boolean;
    children: React.ReactNode;
    badge?: string;
}

export const Accordion: React.FC<AccordionProps> = ({
    title,
    defaultOpen = false,
    children,
    badge
}) => {
    const [isOpen, setIsOpen] = useState(defaultOpen);

    return (
        <div className="border border-white/5 rounded-2xl overflow-hidden bg-white/[0.02] transition-all duration-300">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors"
            >
                <div className="flex items-center space-x-3">
                    <span className="text-[11px] font-black uppercase tracking-[0.15em] text-slate-300">
                        {title}
                    </span>
                    {badge && (
                        <span className="px-2 py-0.5 bg-accent-primary/20 text-accent-primary text-[9px] font-bold rounded-full">
                            {badge}
                        </span>
                    )}
                </div>
                <ChevronDown
                    className={`w-4 h-4 text-slate-500 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
                />
            </button>

            <div
                className={`
                    overflow-hidden transition-all duration-300 ease-out
                    ${isOpen ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'}
                `}
            >
                <div className="px-4 pb-4 pt-1 space-y-4">
                    {children}
                </div>
            </div>
        </div>
    );
};

// Slider subcomponent for Generation Settings
interface SliderProps {
    label: string;
    value: number;
    onChange: (val: number) => void;
    min?: number;
    max?: number;
    unit?: string;
}

export const SettingsSlider: React.FC<SliderProps> = ({
    label,
    value,
    onChange,
    min = 0,
    max = 100,
    unit = '%'
}) => {
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
                <span className="text-[11px] font-mono text-accent-primary">{value}{unit}</span>
            </div>
            <div className="relative h-2 bg-black/40 rounded-full overflow-hidden">
                <div
                    className="absolute inset-y-0 left-0 bg-gradient-to-r from-accent-primary to-accent-secondary rounded-full transition-all"
                    style={{ width: `${((value - min) / (max - min)) * 100}%` }}
                />
                <input
                    type="range"
                    min={min}
                    max={max}
                    value={value}
                    onChange={(e) => onChange(Number(e.target.value))}
                    className="absolute inset-0 w-full opacity-0 cursor-pointer"
                />
            </div>
            <div className="flex justify-between text-[9px] text-slate-600 font-medium">
                <span>{min}{unit}</span>
                <span>{max}{unit}</span>
            </div>
        </div>
    );
};
