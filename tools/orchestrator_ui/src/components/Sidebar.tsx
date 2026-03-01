import { motion } from 'framer-motion';
import {
    Network,
    ClipboardList,
    BarChart2,
    Activity,
    Settings,
} from 'lucide-react';

export type SidebarTab =
    | 'graph'
    | 'plans'
    | 'evals'
    | 'metrics'
    | 'security'
    | 'operations'
    | 'settings'
    | 'mastery';

interface SidebarProps {
    activeTab: SidebarTab;
    onTabChange: (tab: SidebarTab) => void;
}

/* ── Tab definitions ─────────────────────────────────────── */

interface TabDef {
    id: SidebarTab;
    icon: typeof Network;
    label: string;
    shortcut?: string;
}

const workflowTabs: TabDef[] = [
    { id: 'graph', icon: Network, label: 'Grafo', shortcut: '1' },
    { id: 'plans', icon: ClipboardList, label: 'Planes', shortcut: '2' },
    { id: 'evals', icon: BarChart2, label: 'Evals', shortcut: '3' },
];

const analyticsTabs: TabDef[] = [
    { id: 'metrics', icon: Activity, label: 'Métricas', shortcut: '4' },
];

const systemTabs: TabDef[] = [
    { id: 'settings', icon: Settings, label: 'Ajustes', shortcut: '5' },
];

/* ── Component ───────────────────────────────────────────── */

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onTabChange }) => {
    const renderTab = ({ id, icon: Icon, label }: TabDef) => {
        const isActive = activeTab === id;

        return (
            <button
                key={id}
                onClick={() => onTabChange(id)}
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
                {/* Active indicator — glow bar */}
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
        <aside
            role="navigation"
            aria-label="Navegación principal"
            className="w-[72px] bg-surface-0/80 backdrop-blur-xl border-r border-white/[0.04] flex flex-col py-3 px-1.5 shrink-0 overflow-y-auto"
        >
            {/* Workflow group */}
            <div className="space-y-1">
                {workflowTabs.map(renderTab)}
            </div>

            {/* Divider */}
            <div className="h-px bg-white/[0.04] mx-3 my-2.5" />

            {/* Analytics group */}
            <div className="space-y-1">
                {analyticsTabs.map(renderTab)}
            </div>

            {/* Spacer */}
            <div className="flex-1" />

            {/* System group — pinned to bottom */}
            <div className="space-y-1">
                {systemTabs.map(renderTab)}
            </div>
        </aside>
    );
};
