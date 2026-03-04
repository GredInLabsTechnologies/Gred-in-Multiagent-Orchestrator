import React from 'react';
import { motion } from 'framer-motion';
import { Network, ClipboardList, Settings } from 'lucide-react';
import { useAppStore, SidebarTab } from '../stores/appStore';

interface TabDef {
    id: SidebarTab;
    icon: typeof Network;
    label: string;
}

const tabs: TabDef[] = [
    { id: 'graph', icon: Network, label: 'Grafo' },
    { id: 'plans', icon: ClipboardList, label: 'Planes' },
];

export const Sidebar: React.FC = () => {
    const activeTab = useAppStore((s) => s.activeTab);
    const setActiveTab = useAppStore((s) => s.setActiveTab);
    const openOverlay = useAppStore((s) => s.openOverlay);

    const renderTab = ({ id, icon: Icon, label }: TabDef) => {
        const isActive = activeTab === id;

        return (
            <button
                key={id}
                onClick={() => setActiveTab(id)}
                aria-label={label}
                aria-current={isActive ? 'page' : undefined}
                className={`
                    w-full relative px-2 py-2.5 rounded-xl flex flex-col items-center justify-center gap-1.5
                    transition-all duration-200 group active:scale-[0.96]
                    ${isActive
                        ? 'text-accent-primary'
                        : 'text-text-secondary hover:text-text-primary'}
                `}
            >
                {/* Active indicator — animated background */}
                {isActive && (
                    <motion.div
                        layoutId="sidebar-active"
                        className="absolute inset-0 rounded-xl bg-accent-primary/10 border border-accent-primary/20"
                        style={{ boxShadow: '0 0 20px rgba(59, 130, 246, 0.08)' }}
                        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                    />
                )}

                {/* Left accent bar */}
                {isActive && (
                    <motion.div
                        layoutId="sidebar-bar"
                        className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-primary"
                        style={{ boxShadow: '0 0 8px var(--glow-primary)' }}
                        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                    />
                )}

                <Icon size={20} className="relative z-10" />
                <span className="relative z-10 text-[9px] font-semibold uppercase tracking-wider leading-none">
                    {label}
                </span>

                {/* Hover glass effect */}
                {!isActive && (
                    <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 bg-surface-3/30 backdrop-blur-sm border border-white/[0.03] transition-opacity duration-200" />
                )}
            </button>
        );
    };

    return (
        <nav
            aria-label="Navegación principal"
            className="w-[72px] bg-surface-0/80 backdrop-blur-xl border-r border-white/[0.04] flex flex-col py-3 px-1.5 shrink-0"
        >
            {/* Primary tabs */}
            <div className="space-y-1">
                {tabs.map(renderTab)}
            </div>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Settings gear — opens overlay */}
            <button
                onClick={() => openOverlay('settings')}
                aria-label="Ajustes"
                className="w-full px-2 py-2.5 rounded-xl flex flex-col items-center justify-center gap-1.5 text-text-secondary hover:text-text-primary transition-all duration-200 group active:scale-[0.96] relative"
            >
                <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 bg-surface-3/30 backdrop-blur-sm border border-white/[0.03] transition-opacity duration-200" />
                <Settings size={20} className="relative z-10" />
                <span className="relative z-10 text-[9px] font-semibold uppercase tracking-wider leading-none">Ajustes</span>
            </button>
        </nav>
    );
};

/**
 * Re-export SidebarTab from store for backward compatibility
 * with components that import from Sidebar.
 */
export type { SidebarTab } from '../stores/appStore';
