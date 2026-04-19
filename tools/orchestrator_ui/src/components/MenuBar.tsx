import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, Server } from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { useProviders } from '../hooks/useProviders';

type MenuId = 'file' | 'edit' | 'connections' | 'tools' | 'help';

interface MenuBarProps {
    status?: any;
    onSelectView: (target: string) => void;
    onOpenSettings: () => void;
    onRefreshSession: () => void;
    onOpenCommandPalette: () => void;
    onMcpSync: () => void;
    onOpenConnections: () => void;
    userDisplayName?: string;
    userEmail?: string;
    userPhotoUrl?: string;
    onOpenProfile?: () => void;
}

interface MenuAction {
    label: string;
    shortcut?: string;
    onClick: () => void;
}

export const MenuBar: React.FC<MenuBarProps> = ({
    status,
    onSelectView,
    onOpenSettings,
    onRefreshSession,
    onOpenCommandPalette,
    onMcpSync,
    onOpenConnections,
    userDisplayName,
    userEmail,
    userPhotoUrl,
    onOpenProfile,
}) => {
    const [openMenu, setOpenMenu] = useState<MenuId | null>(null);
    const [isAboutOpen, setIsAboutOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement | null>(null);
    const activeTab = useAppStore((s) => s.activeTab);
    const { effectiveState, loadProviders } = useProviders();

    useEffect(() => {
        loadProviders();
    }, [loadProviders]);

    const healthBadgeClass = useMemo(() => {
        const health = String(effectiveState?.health || '').toLowerCase();
        if (health === 'ok') return 'bg-emerald-500 shadow-[0_0_8px_rgba(16,218,133,0.6)]';
        if (health === 'degraded') return 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]';
        if (health === 'down') return 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]';
        return 'bg-surface-3';
    }, [effectiveState?.health]);

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
            { label: 'Nuevo Plan', shortcut: '⌘N', onClick: () => onSelectView('graph') },
            { label: 'Abrir Repo', onClick: () => onSelectView('operations') },
            { label: 'Revalidar sesión', onClick: onRefreshSession },
        ],
        edit: [
            { label: 'Preferencias', shortcut: '⌘,', onClick: onOpenSettings },
            { label: 'Configurar proveedores', onClick: onOpenConnections },
            { label: 'Configurar economía', onClick: () => onSelectView('mastery') },
            { label: 'Políticas de seguridad', onClick: () => onSelectView('security') },
        ],
        connections: [
            { label: 'Abrir Conexiones', onClick: onOpenConnections },
            { label: 'Estado de conexión', onClick: () => onOpenConnections() },
        ],
        tools: [
            { label: 'Command Palette', shortcut: '⌘K', onClick: onOpenCommandPalette },
            { label: 'Economía', onClick: () => onSelectView('mastery') },
            { label: 'Seguridad', onClick: () => onSelectView('security') },
            { label: 'Centro Operativo', onClick: () => onSelectView('operations') },
            { label: 'MCP Sync', onClick: onMcpSync },
            { label: 'Ejecutar Evaluación', onClick: () => onSelectView('evals') },
        ],
        help: [
            { label: 'Tutorial rápido', onClick: () => window.open('https://github.com/GredInLabsTechnologies/Gred-in-Multiagent-Orchestrator/blob/main/docs/SETUP.md', '_blank') },
            { label: 'Documentación', onClick: () => window.open('https://github.com/GredInLabsTechnologies/Gred-in-Multiagent-Orchestrator#readme', '_blank') },
            { label: 'Acerca de GIMO', onClick: () => setIsAboutOpen(true) },
        ],
    }), [onMcpSync, onOpenCommandPalette, onRefreshSession, onOpenSettings, onSelectView, onOpenConnections]);

    const labels: Record<MenuId, string> = {
        file: 'Archivo',
        edit: 'Editar',
        connections: 'Conexiones',
        tools: 'Herramientas',
        help: 'Ayuda',
    };

    /* ── Breadcrumb ── */
    const tabLabels: Record<string, string> = {
        graph: 'Graph',
        plans: 'Plans',
        evals: 'Evaluations',
        metrics: 'Metrics',
        mastery: 'Economy',
        security: 'Security',
        operations: 'Operations',
        settings: 'Settings',
    };

    const profileLabel = userDisplayName || userEmail || 'Profile';
    const profileInitial = (profileLabel || 'U').trim().charAt(0).toUpperCase();

    return (
        <header className="h-10 border-b border-white/[0.04] bg-surface-0/60 backdrop-blur-2xl px-3 flex items-center justify-between shrink-0 z-50">
            {/* Left: menus */}
            <div ref={rootRef} className="flex items-center gap-0.5">
                {(Object.keys(labels) as MenuId[]).map((id) => (
                    <div key={id} className="relative">
                        <button
                            onClick={() => {
                                if (id === 'connections') {
                                    setOpenMenu(null);
                                    onOpenConnections();
                                    return;
                                }
                                setOpenMenu((prev: MenuId | null) => (prev === id ? null : id));
                            }}
                            className={`h-7 px-2.5 rounded-lg text-[11px] font-medium inline-flex items-center gap-1 transition-all duration-150 active:scale-[0.97] ${openMenu === id
                                ? 'bg-white/[0.08] text-text-primary'
                                : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                                }`}
                        >
                            {labels[id]}
                            {id === 'connections' ? (
                                <>
                                    <div className={`w-2 h-2 rounded-full ${healthBadgeClass}`} />
                                    <Server size={10} className="text-text-secondary" />
                                </>
                            ) : (
                                <ChevronDown
                                    size={10}
                                    className={`transition-transform duration-200 ${openMenu === id ? 'rotate-180' : ''}`}
                                />
                            )}
                        </button>

                        <AnimatePresence>
                            {id !== 'connections' && openMenu === id && (
                                <motion.div
                                    initial={{ opacity: 0, y: -4, scale: 0.98 }}
                                    animate={{ opacity: 1, y: 0, scale: 1 }}
                                    exit={{ opacity: 0, y: -4, scale: 0.98 }}
                                    transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
                                    className="absolute top-full left-0 mt-1 w-56 rounded-xl border border-white/[0.06] bg-surface-1/90 backdrop-blur-2xl shadow-xl shadow-black/30 overflow-hidden z-50"
                                >
                                    {menus[id].map((entry) => (
                                        <button
                                            key={entry.label}
                                            onClick={() => {
                                                entry.onClick();
                                                setOpenMenu(null);
                                            }}
                                            className="w-full text-left px-3 py-2 text-[11px] text-text-primary hover:bg-white/[0.06] transition-colors duration-100 flex items-center justify-between"
                                        >
                                            <span>{entry.label}</span>
                                            {entry.shortcut && (
                                                <span className="text-text-tertiary text-[10px] font-mono">{entry.shortcut}</span>
                                            )}
                                        </button>
                                    ))}
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                ))}
            </div>

            {/* Center: breadcrumb */}
            <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-wider">
                <span className="text-accent-primary font-bold">GIMO</span>
                <span className="text-text-tertiary">/</span>
                <span className="text-text-secondary">{tabLabels[activeTab] || activeTab}</span>
            </div>

            <div className="flex items-center gap-2 min-w-[180px] justify-end">

                <button
                    onClick={() => {
                        setOpenMenu(null);
                        onOpenProfile?.();
                    }}
                    className="inline-flex items-center gap-2 rounded-full pl-1 pr-2.5 py-1 border border-white/[0.06] bg-surface-1/60 backdrop-blur-lg hover:bg-white/[0.06] transition-all duration-200"
                    title="Abrir Mi Perfil"
                >
                    <span className="w-6 h-6 rounded-full overflow-hidden border border-white/[0.08] bg-surface-3 flex items-center justify-center text-[10px] font-bold text-text-primary">
                        {userPhotoUrl ? (
                            <img src={userPhotoUrl} alt="Avatar" className="w-full h-full object-cover" />
                        ) : (
                            profileInitial
                        )}
                    </span>
                    <span className="max-w-[100px] truncate text-[11px] text-text-secondary">{profileLabel}</span>
                </button>
            </div>

            {/* About modal */}
            <AnimatePresence>
                {isAboutOpen && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
                        onClick={() => setIsAboutOpen(false)}
                    >
                        <motion.div
                            initial={{ scale: 0.95, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.95, opacity: 0 }}
                            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                            className="bg-surface-1/90 backdrop-blur-2xl border border-white/[0.06] rounded-2xl w-96 overflow-hidden shadow-2xl relative"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="p-6 text-center space-y-4">
                                <div className="w-16 h-16 bg-accent-primary/10 border border-accent-primary/20 rounded-2xl flex items-center justify-center mx-auto mb-2">
                                    <span className="text-2xl font-black text-accent-primary">G</span>
                                </div>
                                <h2 className="text-lg font-bold text-text-primary">GIMO Phoenix</h2>
                                <p className="text-xs text-text-secondary px-4">
                                    Orquestación multi-agente con capacidades avanzadas.
                                </p>

                                <div className="bg-black/20 rounded-xl p-4 border border-white/[0.04] space-y-3 mt-4 text-left">
                                    {[
                                        ['Versión', `v${status?.version || '1.0.0-rc.1'}`, 'text-accent-primary'],
                                        ['Estado', status?.service_status || 'Operativo', 'text-emerald-400'],
                                        ['Uptime', status?.uptime_seconds ? `${Math.floor(status.uptime_seconds / 3600)}h ${Math.floor((status.uptime_seconds % 3600) / 60)}m` : '0h 0m', 'text-text-primary'],
                                    ].map(([label, value, color]) => (
                                        <div key={label} className="flex justify-between items-center border-b border-white/[0.04] pb-2 last:border-0 last:pb-0">
                                            <span className="text-xs text-text-secondary">{label}</span>
                                            <span className={`text-[11px] font-mono ${color}`}>{value}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            <div className="px-6 py-4 bg-white/[0.02] border-t border-white/[0.04] flex justify-end">
                                <button
                                    onClick={() => setIsAboutOpen(false)}
                                    className="px-5 py-2 bg-accent-primary hover:bg-accent-primary/85 text-white rounded-xl text-xs font-bold transition-all active:scale-[0.96]"
                                >
                                    Continuar
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </header>
    );
};
