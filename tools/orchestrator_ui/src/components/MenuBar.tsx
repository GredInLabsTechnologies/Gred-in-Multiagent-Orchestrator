import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { SidebarTab } from './Sidebar';

type MenuId = 'file' | 'edit' | 'view' | 'tools' | 'help';

interface MenuBarProps {
    status?: any;
    onNewPlan: () => void;
    onSelectView: (tab: SidebarTab) => void;
    onSelectSettingsView: (tab: SidebarTab) => void;
    onRefreshSession: () => void;
    onOpenCommandPalette: () => void;
    onMcpSync: () => void;
    userDisplayName?: string;
    userEmail?: string;
    userPhotoUrl?: string;
    onOpenProfile?: () => void;
}

interface MenuAction {
    label: string;
    onClick: () => void;
}

export const MenuBar: React.FC<MenuBarProps> = ({
    status,
    onNewPlan,
    onSelectView,
    onSelectSettingsView,
    onRefreshSession,
    onOpenCommandPalette,
    onMcpSync,
    userDisplayName,
    userEmail,
    userPhotoUrl,
    onOpenProfile,
}) => {
    const [openMenu, setOpenMenu] = useState<MenuId | null>(null);
    const [isAboutOpen, setIsAboutOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
                setOpenMenu(null);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const menus = useMemo<Record<MenuId, MenuAction[]>>(() => ({
        file: [
            { label: 'Nuevo Plan', onClick: onNewPlan },
            { label: 'Abrir Repo', onClick: () => onSelectView('operations') },
            { label: 'Revalidar sesión', onClick: onRefreshSession },
        ],
        edit: [
            { label: 'Config Economía', onClick: () => onSelectSettingsView('mastery') },
            { label: 'Config Providers', onClick: () => onSelectSettingsView('settings') },
            { label: 'Políticas / Seguridad', onClick: () => onSelectSettingsView('security') },
        ],
        view: [
            { label: 'Graph', onClick: () => onSelectView('graph') },
            { label: 'Planes', onClick: () => onSelectView('plans') },
            { label: 'Evaluaciones', onClick: () => onSelectView('evals') },
            { label: 'Métricas', onClick: () => onSelectView('metrics') },
            { label: 'Seguridad', onClick: () => onSelectView('security') },
            { label: 'Mantenimiento', onClick: () => onSelectView('operations') },
        ],
        tools: [
            { label: 'Command Palette (Ctrl+K)', onClick: onOpenCommandPalette },
            { label: 'MCP Sync', onClick: onMcpSync },
            { label: 'Ejecutar Evaluación', onClick: () => onSelectView('evals') },
        ],
        help: [
            { label: 'Documentación', onClick: () => window.open('https://github.com/GredInLabsTechnologies/Gred-in-Multiagent-Orchestrator#readme', '_blank') },
            { label: 'Acerca de GIMO', onClick: () => setIsAboutOpen(true) },
        ],
    }), [onMcpSync, onNewPlan, onOpenCommandPalette, onRefreshSession, onSelectSettingsView, onSelectView]);

    const labels: Record<MenuId, string> = {
        file: 'Archivo',
        edit: 'Editar',
        view: 'Ver',
        tools: 'Herramientas',
        help: 'Ayuda',
    };

    const profileLabel = userDisplayName || userEmail || 'Mi Perfil';
    const profileInitial = (profileLabel || 'U').trim().charAt(0).toUpperCase();

    return (
        <header className="h-10 border-b border-border-primary bg-surface-0/90 backdrop-blur-xl px-3 flex items-center justify-between shrink-0 z-50">
            <div ref={rootRef} className="flex items-center gap-1">
                {(Object.keys(labels) as MenuId[]).map((id) => (
                    <div key={id} className="relative">
                        <button
                            onClick={() => setOpenMenu(prev => prev === id ? null : id)}
                            className={`h-7 px-2.5 rounded-md text-xs font-medium inline-flex items-center gap-1 transition-colors active:scale-[0.97] ${openMenu === id
                                ? 'bg-surface-3 text-text-primary'
                                : 'text-text-secondary hover:text-text-primary hover:bg-surface-3/70'
                                }`}
                        >
                            {labels[id]}
                            <ChevronDown size={12} className={`transition-transform ${openMenu === id ? 'rotate-180' : ''}`} />
                        </button>

                        {openMenu === id && (
                            <div className="absolute top-full left-0 mt-1 w-56 rounded-xl border border-border-primary bg-surface-2 shadow-2xl overflow-hidden animate-slide-in-down">
                                {menus[id].map((entry) => (
                                    <button
                                        key={entry.label}
                                        onClick={() => {
                                            entry.onClick();
                                            setOpenMenu(null);
                                        }}
                                        className="w-full text-left px-3 py-2 text-xs text-text-primary hover:bg-surface-3 transition-colors duration-100"
                                    >
                                        {entry.label}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <div className="text-[10px] text-text-secondary font-mono uppercase tracking-wider">GIMO</div>

            <div className="flex items-center gap-2 min-w-[140px] justify-end">
                <button
                    onClick={() => {
                        setOpenMenu(null);
                        onOpenProfile?.();
                    }}
                    className="inline-flex items-center gap-2 rounded-full pl-1 pr-2 py-1 border border-border-primary bg-surface-1 hover:bg-surface-3 transition-colors"
                    title="Abrir Mi Perfil"
                >
                    <span className="w-7 h-7 rounded-full overflow-hidden border border-border-primary bg-surface-3 flex items-center justify-center text-[11px] font-bold text-text-primary">
                        {userPhotoUrl ? (
                            <img src={userPhotoUrl} alt="Avatar" className="w-full h-full object-cover" />
                        ) : (
                            profileInitial
                        )}
                    </span>
                    <span className="max-w-[120px] truncate text-xs text-text-primary">{profileLabel}</span>
                </button>
            </div>

            {isAboutOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                    <div className="bg-surface-2 border border-border-primary rounded-2xl w-96 overflow-hidden shadow-2xl relative">
                        <div className="p-6 text-center space-y-4">
                            <div className="w-16 h-16 bg-surface-3 rounded-3xl flex items-center justify-center mx-auto mb-2 text-accent-primary">
                                <span className="text-2xl font-bold">G</span>
                            </div>
                            <h2 className="text-xl font-bold text-text-primary">Interfaz de Usuario GIMO Phoenix</h2>
                            <p className="text-xs text-text-secondary px-4">Aumentando la orquestación multi-agente con capacidades avanzadas.</p>

                            <div className="bg-black/30 rounded-xl p-4 border border-white/5 space-y-3 mt-4 text-left">
                                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                                    <span className="text-xs text-text-secondary">Versión</span>
                                    <span className="text-[11px] font-mono text-accent-primary">v{status?.version || '1.0.0-rc.1'}</span>
                                </div>
                                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                                    <span className="text-xs text-text-secondary">Estado del Servicio</span>
                                    <span className="text-[11px] font-mono text-emerald-400">{status?.service_status || 'Operativo'}</span>
                                </div>
                                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                                    <span className="text-xs text-text-secondary">Tiempo Activo</span>
                                    <span className="text-[11px] font-mono text-text-primary">{status?.uptime ? `${Math.floor(status.uptime / 3600)}h ${Math.floor((status.uptime % 3600) / 60)}m` : '0h 0m'}</span>
                                </div>
                                <div className="flex justify-between items-center">
                                    <span className="text-xs text-text-secondary">Repositorio Activo</span>
                                    <span className="text-[10px] font-mono text-text-primary truncate max-w-[140px]" title={status?.active_workspace || 'N/A'}>
                                        {status?.active_workspace ? status.active_workspace.split(/[\\/]/).pop() : 'N/A'}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div className="px-6 py-4 bg-surface-3/50 border-t border-border-primary flex justify-end">
                            <button
                                onClick={() => setIsAboutOpen(false)}
                                className="px-5 py-2 bg-accent-primary hover:bg-accent-primary/85 text-white rounded-xl text-xs font-bold transition-all hover:scale-105 active:scale-95"
                            >
                                Continuar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </header>
    );
};
