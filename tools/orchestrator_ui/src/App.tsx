import { useEffect, useCallback, lazy, Suspense } from 'react';
import { useAppStore, SidebarTab } from './stores/appStore';
import { checkSession, logout } from './lib/auth';
import { getCommandHandlers } from './lib/commands';
import { Sidebar, SidebarTab as LegacySidebarTab } from './components/Sidebar';
import { MenuBar } from './components/MenuBar';
import { StatusBar } from './components/StatusBar';
import { LoginModal } from './components/LoginModal';
import { CommandPalette } from './components/Shell/CommandPalette';
import { ProfilePanel } from './components/ProfilePanel';
import { useToast } from './components/Toast';
import { useProfile } from './hooks/useProfile';
import { useProviderHealth } from './hooks/useProviderHealth';
import { UiStatusResponse, API_BASE } from './types';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useState } from 'react';

/* ── Lazy-loaded views ─────────────────────────────────── */
const GraphView = lazy(() => import('./views/GraphView'));
const PlansView = lazy(() => import('./views/PlansView'));
const EvalDashboard = lazy(() => import('./components/evals/EvalDashboard').then(m => ({ default: m.EvalDashboard })));
const ObservabilityPanel = lazy(() => import('./components/observability/ObservabilityPanel').then(m => ({ default: m.ObservabilityPanel })));
const TrustSettingsView = lazy(() => import('./views/TrustSettingsView'));
const MaintenanceView = lazy(() => import('./views/MaintenanceView'));
const SettingsPanel = lazy(() => import('./components/SettingsPanel').then(m => ({ default: m.SettingsPanel })));
const TokenMasteryView = lazy(() => import('./views/TokenMasteryView'));

/* ── Loading fallback ──────────────────────────────────── */
const ViewLoader = () => (
    <div className="h-full flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
    </div>
);

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

    /* ── Boot: check session on mount ── */
    useEffect(() => { void checkSession(); }, []);

    /* ── Poll status when authenticated ── */
    useEffect(() => {
        if (!store.authenticated) return;
        const fetchStatus = async () => {
            try {
                const res = await fetch(`${API_BASE}/ui/status`, { credentials: 'include' });
                if (res.status === 401) { store.setAuthenticated(false); return; }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                setStatus(data);
                store.setBootState('ready');
                store.setBootError(null);
            } catch {
                addToast('No hay conexión con el backend.', 'error');
                store.setBootState('offline');
                store.setBootError('No hay conexión con el backend.');
            }
        };
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, [store.authenticated]);

    /* ── Keyboard: Ctrl+K command palette ── */
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

    /* ── Auto-refresh graph count when on graph tab with 0 nodes ── */
    useEffect(() => {
        if (!store.authenticated || store.activeTab !== 'graph' || store.graphNodeCount !== 0) return;
        const refresh = async () => {
            try {
                const res = await fetch(`${API_BASE}/ui/graph`, { credentials: 'include' });
                if (!res.ok) return;
                const payload = await res.json();
                const count = Array.isArray(payload?.nodes) ? payload.nodes.length : 0;
                store.setGraphNodeCount(count);
            } catch { /* welcome screen stays visible */ }
        };
        const interval = setInterval(refresh, 5000);
        return () => clearInterval(interval);
    }, [store.authenticated, store.activeTab, store.graphNodeCount]);

    /* ── Session expiry watch ── */
    useEffect(() => {
        if (!store.authenticated || !profileUnauthorized) return;
        addToast('Sesión expirada. Vuelve a iniciar sesión.', 'info');
        void logout();
    }, [store.authenticated, profileUnauthorized]);

    /* ── Command palette handler ── */
    const commandHandlers = getCommandHandlers(addToast);
    const handleCommandAction = useCallback(
        (actionId: string) => {
            const handler = commandHandlers[actionId];
            if (handler) void handler();
        },
        [commandHandlers],
    );

    /* ── Plan engine (kept for PlansPanel compat) ── */
    // TODO: move to PlansView in Phase 1
    const handleApprovePlanFromGraph = useCallback(async (draftId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/approve`, {
                method: 'POST', credentials: 'include',
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan aprobado exitosamente', 'success');
            store.setGraphNodeCount(-1);
        } catch { addToast('Error al aprobar el plan', 'error'); }
    }, [addToast]);

    const handleRejectPlan = useCallback(async (draftId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/reject`, {
                method: 'POST', credentials: 'include',
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan rechazado', 'info');
            store.setGraphNodeCount(0);
        } catch { addToast('Error al rechazar el plan', 'error'); }
    }, [addToast]);

    /* ── Render: boot states ── */
    if (store.bootState === 'checking' || store.authenticated === null) {
        return (
            <div className="min-h-screen bg-surface-0 flex items-center justify-center">
                <div className="flex flex-col items-center gap-4">
                    <div className="w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
                    <span className="text-xs text-text-secondary tracking-widest uppercase">Iniciando GIMO</span>
                </div>
            </div>
        );
    }

    if (store.bootState === 'offline') {
        return (
            <div className="min-h-screen bg-surface-0 text-text-primary flex items-center justify-center p-6">
                <div className="w-full max-w-lg rounded-2xl border border-border-primary bg-surface-2 p-8 space-y-5">
                    <div className="flex items-center gap-3 text-accent-warning">
                        <AlertTriangle size={20} />
                        <h1 className="text-lg font-semibold">Backend no disponible</h1>
                    </div>
                    <p className="text-sm text-text-secondary">
                        {store.bootError || 'No se pudo conectar con los servicios de GIMO.'}
                    </p>
                    <button
                        onClick={() => void checkSession()}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-accent-primary hover:bg-accent-primary/85 text-white text-sm font-medium"
                    >
                        <RefreshCw size={14} />
                        Reintentar conexión
                    </button>
                </div>
            </div>
        );
    }

    if (!store.authenticated) {
        return <LoginModal onAuthenticated={() => void checkSession()} />;
    }

    /* ── Render: main app ── */
    const displayName = profile?.user?.displayName || store.sessionUser?.displayName || store.sessionUser?.email || 'Mi Perfil';
    const email = profile?.user?.email || store.sessionUser?.email;

    const renderView = () => {
        switch (store.activeTab) {
            case 'graph':
                return (
                    <GraphView
                        providerHealth={providerHealth}
                        graphNodeCount={store.graphNodeCount}
                        onGraphNodeCountChange={store.setGraphNodeCount}
                        onApprovePlan={handleApprovePlanFromGraph}
                        onRejectPlan={handleRejectPlan}
                        onNewPlan={() => store.setActiveTab('plans')}
                        activePlanIdFromChat={store.activePlanIdFromChat}
                    />
                );
            case 'plans':
                return <PlansView />;
            case 'evals':
                return <EvalDashboard />;
            case 'metrics':
                return <ObservabilityPanel />;
            case 'security':
                return <TrustSettingsView />;
            case 'operations':
                return <MaintenanceView />;
            case 'settings':
                return <SettingsPanel onOpenMastery={() => store.setActiveTab('mastery')} />;
            case 'mastery':
                return <TokenMasteryView />;
            default:
                return null;
        }
    };

    return (
        <div className="min-h-screen bg-surface-0 text-text-primary font-sans selection:bg-accent-primary selection:text-white flex flex-col">
            <MenuBar
                status={status}
                onNewPlan={() => store.setActiveTab('plans')}
                onSelectView={(tab: SidebarTab) => store.setActiveTab(tab)}
                onSelectSettingsView={(tab: SidebarTab) => store.setActiveTab(tab)}
                onRefreshSession={() => void checkSession()}
                onOpenCommandPalette={() => store.toggleCommandPalette(true)}
                onMcpSync={() => {
                    const handlers = getCommandHandlers(addToast);
                    void handlers.mcp_sync();
                }}
                userDisplayName={displayName}
                userEmail={email}
                userPhotoUrl={profile?.user?.photoURL}
                onOpenProfile={() => store.toggleProfile(true)}
            />

            <div className="flex flex-1 overflow-hidden">
                <Sidebar
                    activeTab={store.activeTab as LegacySidebarTab}
                    onTabChange={(tab) => store.setActiveTab(tab)}
                />
                <main role="main" className="flex-1 relative overflow-hidden">
                    <Suspense fallback={<ViewLoader />}>
                        {renderView()}
                    </Suspense>
                </main>
            </div>

            <StatusBar
                providerHealth={providerHealth}
                version={status?.version}
                serviceStatus={status?.service_status}
                onNavigateToSettings={() => store.setActiveTab('settings')}
                onNavigateToMastery={() => store.setActiveTab('mastery')}
            />

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
