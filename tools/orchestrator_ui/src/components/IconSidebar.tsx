/*
COMPONENT: IconSidebar
ROLE: Vertical icon navigation bar on the left edge
CONTEXT: Provides quick access to main sections. Icons will be customized later.
LAST_MODIFIED: 2026-01-21
*/

import React from 'react';
import {
    Brush,
    MousePointer2,
    Shapes,
    Layers,
    Play,
    Settings,
    LucideIcon
} from 'lucide-react';

interface IconSidebarProps {
    activeSection: string;
    onSectionChange: (section: string) => void;
}

interface NavItem {
    id: string;
    icon: LucideIcon;
    label: string;
}

// Placeholder icons - will be customized later
const NAV_ITEMS: NavItem[] = [
    { id: 'brush', icon: Brush, label: 'Creative' },
    { id: 'pointer', icon: MousePointer2, label: 'Select' },
    { id: 'shapes', icon: Shapes, label: 'Shapes' },
    { id: 'layers', icon: Layers, label: 'Layers' },
    { id: 'animation', icon: Play, label: 'Animation' },
];

const BOTTOM_ITEMS: NavItem[] = [
    { id: 'settings', icon: Settings, label: 'Settings' },
];

export const IconSidebar: React.FC<IconSidebarProps> = ({
    activeSection,
    onSectionChange
}) => {
    return (
        <aside className="w-12 h-full flex flex-col items-center py-4 bg-white/[0.02] border-r border-white/5 relative z-30">
            {/* Glow line on left edge */}
            <div className="absolute left-0 top-1/4 bottom-1/4 w-[2px] bg-gradient-to-b from-transparent via-accent-primary/30 to-transparent" />

            {/* Top Icons */}
            <div className="flex flex-col items-center space-y-2 flex-1">
                {NAV_ITEMS.map((item) => {
                    const Icon = item.icon;
                    const isActive = activeSection === item.id;

                    return (
                        <button
                            key={item.id}
                            onClick={() => onSectionChange(item.id)}
                            className={`
                                relative w-10 h-10 rounded-xl flex items-center justify-center
                                transition-all duration-300 group
                                ${isActive
                                    ? 'bg-accent-primary/20 text-accent-primary shadow-[0_0_20px_rgba(124,58,237,0.3)]'
                                    : 'text-slate-500 hover:text-white hover:bg-white/5'
                                }
                            `}
                            title={item.label}
                        >
                            {/* Active indicator */}
                            {isActive && (
                                <div className="absolute -left-[5px] top-1/2 -translate-y-1/2 w-[3px] h-5 bg-accent-primary rounded-r-full shadow-[0_0_10px_rgba(124,58,237,0.5)]" />
                            )}

                            <Icon className={`w-5 h-5 transition-transform ${isActive ? 'scale-110' : 'group-hover:scale-110'}`} />

                            {/* Tooltip */}
                            <div className="absolute left-full ml-3 px-2 py-1 bg-black/90 backdrop-blur-xl border border-white/10 rounded-lg text-[10px] font-bold text-white uppercase tracking-wider opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
                                {item.label}
                            </div>
                        </button>
                    );
                })}
            </div>

            {/* Divider */}
            <div className="w-6 h-px bg-white/10 my-4" />

            {/* Bottom Icons */}
            <div className="flex flex-col items-center space-y-2">
                {BOTTOM_ITEMS.map((item) => {
                    const Icon = item.icon;
                    const isActive = activeSection === item.id;

                    return (
                        <button
                            key={item.id}
                            onClick={() => onSectionChange(item.id)}
                            className={`
                                relative w-10 h-10 rounded-xl flex items-center justify-center
                                transition-all duration-300 group
                                ${isActive
                                    ? 'bg-accent-primary/20 text-accent-primary'
                                    : 'text-slate-500 hover:text-white hover:bg-white/5'
                                }
                            `}
                            title={item.label}
                        >
                            <Icon className="w-5 h-5" />

                            {/* Tooltip */}
                            <div className="absolute left-full ml-3 px-2 py-1 bg-black/90 backdrop-blur-xl border border-white/10 rounded-lg text-[10px] font-bold text-white uppercase tracking-wider opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
                                {item.label}
                            </div>
                        </button>
                    );
                })}
            </div>
        </aside>
    );
};
