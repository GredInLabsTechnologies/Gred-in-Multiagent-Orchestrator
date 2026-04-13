import { lazy, Suspense, useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useAppStore } from './stores/appStore';
import { useToast } from './components/Toast';
import { useProfile } from './hooks/useProfile';
import { useProviderHealth } from './hooks/useProviderHealth';
import { checkSession, logout } from './lib/auth';
import { API_BASE, UiStatusResponse } from './types';
import { fetchWithRetry } from './lib/fetchWithRetry';
import { fetchOperatorStatus } from './lib/operatorStatus';
import { getCommandHandlers } from './lib/commands';
import { LoginModal } from './components/LoginModal';
import { MenuBar } from './components/MenuBar';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { OverlayDrawer } from './components/OverlayDrawer';
import { CommandPalette } from './components/Shell/CommandPalette';
import { ProfilePanel } from './components/ProfilePanel';
import { useSkillNotifications } from './hooks/useSkillNotifications';
import { useNetworkStatus } from './hooks/useNetworkStatus';
import { BackgroundRunner } from './components/BackgroundRunner';
import { SkillsRail } from './components/SkillsRail';
/* ── Lazy-loaded views ─────────────────────────────────── */
const GraphView = lazy(() => import('./views/GraphView'));
const PlansView = lazy(() => import('./views/PlansView'));

/* Overlay content (lazy) */
const SettingsPanel = lazy(() => import('./components/SettingsPanel').then(m => ({ default: m.SettingsPanel })));
const ProviderSettings = lazy(() => import('./components/ProviderSettings').then(m => ({ default: m.ProviderSettings })));
const EvalDashboard = lazy(() => import('./components/evals/EvalDashboard').then(m => ({ default: m.EvalDashboard })));
const ObservabilityPanel = lazy(() => import('./components/observability/ObservabilityPanel').then(m => ({ default: m.ObservabilityPanel })));
const TrustSettings = lazy(() => import('./components/TrustSettings').then(m => ({ default: m.TrustSettings })));
const MaintenanceIsland = lazy(() => import('./islands/system/MaintenanceIsland').then(m => ({ default: m.MaintenanceIsland })));
const TokenMastery = lazy(() => import('./components/TokenMastery').then(m => ({ default: m.TokenMastery })));

/* ── Loading fallback with skeleton ───────────────────── */
const ViewLoader = () => (
    <div className="h-full flex flex-col p-6 gap-4 animate-pulse">
        <div className="h-8 w-48 rounded-lg bg-surface-3/40" />
        <div className="flex-1 flex gap-4">
            <div className="flex-1 flex flex-col gap-3">
                <div className="h-4 w-full rounded bg-surface-3/30" />
                <div className="h-4 w-5/6 rounded bg-surface-3/30" />
                <div className="h-4 w-3/4 rounded bg-surface-3/30" />
                <div className="h-32 w-full rounded-xl bg-surface-3/20 mt-2" />
            </div>
            <div className="w-64 flex flex-col gap-3">
                <div className="h-4 w-full rounded bg-surface-3/30" />
                <div className="h-4 w-2/3 rounded bg-surface-3/30" />
                <div className="h-24 w-full rounded-xl bg-surface-3/20 mt-2" />
            </div>
        </div>
    </div>
);

/* ── Overlay config ────────────────────────────────────── */
const overlayConfig = {
    connections: { title: 'Conexiones y Modelos', width: 'full' as const },
    settings: { title: 'Ajustes', width: 'lg' as const },
    evals: { title: 'Evaluaciones', width: 'xl' as const },
    metrics: { title: 'Métricas & Observabilidad', width: 'xl' as const },
    mastery: { title: 'Economía de Tokens', width: 'lg' as const },
    security: { title: 'Seguridad & Trust', width: 'lg' as const },
    operations: { title: 'Operaciones', width: 'lg' as const },
};

/* ── App ───────────────────────────────────────────────── */
export default function App() {
    const store = useAppStore();
    const { addToast } = useToast();
    const [status, setStatus] = useState<UiStatusResponse | null>(null);

    const {
        profile,
        loading: profileLoading,
        error: profileError,
        unauthorized: profileUnauthorized,
        refetch: refetchProfile,
    } = useProfile(Boolean(store.authenticated));

    const providerHealth = useProviderHealth(Boolean(store.authenticated));
    const { connected: networkConnected } = useNetworkStatus();

    /* ── Realtime Skill Notifications ── */
    useSkillNotifications();

    /* ── Boot ── */
    useEffect(() => { checkSession(); }, []);

    /* ── Poll status ── */
    const authenticated = store.authenticated;
    useEffect(() => {
        if (!authenticated) return;
        const { setAuthenticated, setBootState, setBootError } = useAppStore.getState();
        let toastedOffline = false;
        const fetchStatus = async () => {
            try {
                const data = await fetchOperatorStatus();
                setStatus(data);
                setBootState('ready');
                setBootError(null);
                toastedOffline = false;
            } catch (error) {
                if (error instanceof Error && error.message === 'HTTP 401') { setAuthenticated(false); return; }
                if (!toastedOffline) {
                    addToast('No hay conexión con el backend.', 'error');
                    toastedOffline = true;
                }
                setBootState('offline');
                setBootError('No hay conexión con el backend.');
            }
        };
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, [authenticated]);

    /* ── Ctrl+K ── */
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                store.toggleCommandPalette(true);
            }
        };
        globalThis.addEventListener('keydown', onKeyDown);
        return () => globalThis.removeEventListener('keydown', onKeyDown);
    }, []);

    /* ── Graph count refresh ── */
    useEffect(() => {
        if (!store.authenticated || store.activeTab !== 'graph' || store.graphNodeCount !== 0) return;
        const refresh = async () => {
            try {
                const res = await fetchWithRetry(`${API_BASE}/ops/graph`, { credentials: 'include' });
                if (!res.ok) return;
                const payload = await res.json();
                store.setGraphNodeCount(Array.isArray(payload?.nodes) ? payload.nodes.length : 0);
            } catch { /* welcome screen stays visible */ }
        };
        const interval = setInterval(refresh, 5000);
        return () => clearInterval(interval);
    }, [store.authenticated, store.activeTab, store.graphNodeCount]);

    /* ── Session expiry ── */
    useEffect(() => {
        if (!store.authenticated || !profileUnauthorized) return;
        addToast('Sesión expirada. Vuelve a iniciar sesión.', 'info');
        void logout();
    }, [store.authenticated, profileUnauthorized]);

    /* ── Commands ── */
    const commandHandlers = getCommandHandlers(addToast);
    const handleCommandAction = useCallback(
        (actionId: string) => { commandHandlers[actionId]?.(); },
        [commandHandlers],
    );

    /* ── Stable callbacks ── */
    const stableSetGraphNodeCount = useCallback((n: number) => useAppStore.getState().setGraphNodeCount(n), []);

    /* ── Graph actions ── */
    const handleApprovePlan = useCallback(async (draftId: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/drafts/${draftId}/approve`, { method: 'POST', credentials: 'include' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan aprobado exitosamente', 'success');
            store.setGraphNodeCount(-1);
        } catch { addToast('Error al aprobar el plan', 'error'); }
    }, [addToast]);

    const handleRejectPlan = useCallback(async (draftId: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/drafts/${draftId}/reject`, { method: 'POST', credentials: 'include' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan rechazado', 'info');
            store.setGraphNodeCount(0);
        } catch { addToast('Error al rechazar el plan', 'error'); }
    }, [addToast]);

    /* ── Boot states ── */
    if (store.bootState === 'checking' || store.authenticated === null) {
        return (
            <output className="min-h-screen bg-surface-0 flex items-center justify-center block" aria-label="Iniciando GIMO">
                <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.4, ease: 'easeOut' }}
                    className="flex flex-col items-center gap-5"
                >
                    {/* Animated logo */}
                    <div className="relative">
                        <div className="w-16 h-16 rounded-2xl bg-accent-primary/10 border border-accent-primary/20 flex items-center justify-center animate-glow-pulse">
                            <span className="text-2xl font-black text-accent-primary">G</span>
                        </div>
                        <div className="absolute -inset-2 rounded-3xl border border-accent-primary/10 animate-pulse" />
                    </div>
                    <div className="flex flex-col items-center gap-2">
                        <span className="text-sm font-semibold text-text-primary">GIMO</span>
                        <span className="text-[10px] text-text-tertiary tracking-widest uppercase">Iniciando sistema</span>
                        {/* Progress bar */}
                        <div className="w-40 h-1 rounded-full bg-surface-3/40 overflow-hidden mt-1">
                            <motion.div
                                className="h-full bg-accent-primary rounded-full"
                                initial={{ width: '0%' }}
                                animate={{ width: '85%' }}
                                transition={{ duration: 3, ease: 'easeInOut' }}
                            />
                        </div>
                    </div>
                </motion.div>
            </output>
        );
    }

    if (store.bootState === 'offline') {
        return (
            <div className="min-h-screen bg-surface-0 text-text-primary flex items-center justify-center p-6" role="alert">
                <div className="w-full max-w-lg rounded-2xl border border-white/[0.06] bg-surface-1/80 backdrop-blur-xl p-8 space-y-5 shadow-xl shadow-black/20">
                    <div className="flex items-center gap-3 text-amber-400">
                        <AlertTriangle size={20} />
                        <h1 className="text-lg font-semibold">Backend no disponible</h1>
                    </div>
                    <p className="text-sm text-text-secondary">
                        {store.bootError || 'No se pudo conectar con los servicios de GIMO.'}
                    </p>
                    <button
                        onClick={() => void checkSession()}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-accent-primary hover:bg-accent-primary/85 text-white text-sm font-medium active:scale-[0.97] transition-all"
                    >
                        <RefreshCw size={14} />
                        Reintentar conexion
                    </button>
                </div>
            </div>
        );
    }

    if (!store.authenticated) {
        return <LoginModal onAuthenticated={() => void checkSession()} />;
    }

    /* ── Main render ── */
    const displayName = profile?.user?.displayName || store.sessionUser?.displayName || store.sessionUser?.email || 'Mi Perfil';
    const email = profile?.user?.email || store.sessionUser?.email;

    const renderMainView = () => {
        switch (store.activeTab) {
            case 'graph':
                return (
                    <GraphView
                        providerHealth={providerHealth}
                        graphNodeCount={store.graphNodeCount}
                        onGraphNodeCountChange={stableSetGraphNodeCount}
                        onApprovePlan={handleApprovePlan}
                        onRejectPlan={handleRejectPlan}
                        onNewPlan={() => store.setActiveTab('plans')}
                        activePlanIdFromChat={store.activePlanIdFromChat}
                    />
                );
            case 'plans':
                return <PlansView />;
            default:
                return null;
        }
    };

    const renderOverlayContent = () => {
        switch (store.activeOverlay) {
            case 'connections':
                return (
                    <div className="p-6 h-full">
                        <ProviderSettings />
                    </div>
                );
            case 'settings':
                return <SettingsPanel onOpenMastery={() => store.openOverlay('mastery')} />;
            case 'evals':
                return <EvalDashboard />;
            case 'metrics':
                return <ObservabilityPanel />;
            case 'mastery':
                return <TokenMastery />;
            case 'security':
                return (
                    <div className="p-6">
                        <TrustSettings />
                    </div>
                );
            case 'operations':
                return (
                    <div className="p-6">
                        <MaintenanceIsland />
                    </div>
                );
            default:
                return null;
        }
    };

    const overlayMeta = store.activeOverlay ? overlayConfig[store.activeOverlay] : null;

    return (
        <div className="min-h-screen bg-surface-0 text-text-primary font-sans selection:bg-accent-primary selection:text-white flex flex-col">
            {/* Skip link for keyboard navigation */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[200] focus:px-4 focus:py-2 focus:rounded-lg focus:bg-accent-primary focus:text-white focus:text-sm focus:font-medium"
            >
                Saltar al contenido principal
            </a>
            <MenuBar
                status={status}
                onSelectView={(tab) => store.navigate(tab)}
                onOpenSettings={() => store.openOverlay('settings')}
                onRefreshSession={() => void checkSession()}
                onOpenCommandPalette={() => store.toggleCommandPalette(true)}
                onMcpSync={() => { commandHandlers.mcp_sync?.(); }}
                onOpenConnections={() => store.openOverlay('connections')}
                userDisplayName={displayName}
                userEmail={email}
                userPhotoUrl={profile?.user?.photoURL}
                onOpenProfile={() => store.toggleProfile(true)}
            />

            <div className="flex flex-1 overflow-hidden">
                <Sidebar />
                <main id="main-content" role="main" className="flex-1 relative overflow-hidden">
                    <AnimatePresence mode="wait">
                        <motion.div
                            key={store.activeTab}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.15 }}
                            className="h-full"
                        >
                            <Suspense fallback={<ViewLoader />}>
                                {renderMainView()}
                            </Suspense>
                        </motion.div>
                    </AnimatePresence>
                </main>
            </div>

            <StatusBar
                providerHealth={providerHealth}
                version={status?.version}
                serviceStatus={status?.service_status}
                networkConnected={networkConnected}
                onNavigateToSettings={() => store.openOverlay('settings')}
                onNavigateToMastery={() => store.openOverlay('mastery')}
            />

            <BackgroundRunner />
            <SkillsRail />

            {/* ── Overlay drawers ── */}
            <OverlayDrawer
                isOpen={store.activeOverlay !== null}
                onClose={store.closeOverlay}
                title={overlayMeta?.title ?? ''}
                width={overlayMeta?.width ?? 'md'}
            >
                <Suspense fallback={<ViewLoader />}>
                    {renderOverlayContent()}
                </Suspense>
            </OverlayDrawer>

            {/* ── Global panels ── */}
            <CommandPalette
                isOpen={store.isCommandPaletteOpen}
                onClose={() => store.toggleCommandPalette(false)}
                onAction={handleCommandAction}
            />

            <ProfilePanel
                isOpen={store.isProfileOpen}
                onClose={() => store.toggleProfile(false)}
                profile={profile}
                loading={profileLoading}
                error={profileError}
                onRefresh={() => void refetchProfile()}
                onLogout={() => void logout()}
            />
        </div>
    );
}
