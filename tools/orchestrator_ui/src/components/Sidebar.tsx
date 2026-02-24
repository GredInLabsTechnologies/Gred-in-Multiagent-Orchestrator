import { Network, Wrench, Settings, ClipboardList, BarChart2, Activity, ShieldAlert, Wallet } from 'lucide-react';

export type SidebarTab = 'graph' | 'plans' | 'evals' | 'metrics' | 'security' | 'operations' | 'settings' | 'mastery';

interface SidebarProps {
    activeTab: SidebarTab;
    onTabChange: (tab: SidebarTab) => void;
}

const primaryTabs: { id: SidebarTab; icon: typeof Network; label: string }[] = [
    { id: 'graph', icon: Network, label: 'Grafo' },
    { id: 'plans', icon: ClipboardList, label: 'Planes' },
    { id: 'evals', icon: BarChart2, label: 'Evals' },
    { id: 'metrics', icon: Activity, label: 'Métricas' },
    { id: 'mastery', icon: Wallet, label: 'Economía' },
];

const systemTabs: { id: SidebarTab; icon: typeof Network; label: string }[] = [
    { id: 'security', icon: ShieldAlert, label: 'Seguridad' },
    { id: 'operations', icon: Wrench, label: 'Operaciones' },
    { id: 'settings', icon: Settings, label: 'Ajustes' },
];

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onTabChange }) => {
    const renderTab = ({ id, icon: Icon, label }: { id: SidebarTab; icon: typeof Network; label: string }) => (
        <button
            key={id}
            onClick={() => onTabChange(id)}
            title={label}
            className={`
                w-full px-2 py-2 rounded-xl flex flex-col items-center justify-center gap-1
                transition-all duration-200 group relative
                ${activeTab === id
                    ? 'bg-[#0a84ff]/15 text-[#0a84ff]'
                    : 'text-[#86868b] hover:text-[#f5f5f7] hover:bg-[#1c1c1e]'}
            `}
        >
            <Icon size={16} />
            <span className="text-[9px] font-bold uppercase tracking-wider leading-none">{label}</span>
        </button>
    );

    return (
        <aside className="w-20 bg-[#000000] border-r border-[#2c2c2e] flex flex-col py-3 px-2 gap-2 shrink-0 overflow-y-auto">
            <div className="space-y-1.5">
                {primaryTabs.map(renderTab)}
            </div>

            <div className="h-px bg-[#1c1c1e] my-1" />

            <div className="space-y-1.5">
                {systemTabs.map(renderTab)}
            </div>
        </aside>
    );
};
