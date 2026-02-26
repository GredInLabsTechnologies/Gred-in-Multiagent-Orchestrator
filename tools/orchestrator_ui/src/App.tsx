import { useState, useEffect, useCallback } from 'react';
import { Sidebar, SidebarTab } from './components/Sidebar';
import { GraphCanvas } from './components/GraphCanvas';
import { InspectPanel } from './components/InspectPanel';
import { TokenMastery } from './components/TokenMastery';
import { MaintenanceIsland } from './islands/system/MaintenanceIsland';
import { LoginModal } from './components/LoginModal';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { UiStatusResponse, PlanCreateRequest, API_BASE } from './types';
import { usePlanEngine } from './hooks/usePlanEngine';
import { PlansPanel } from './components/PlansPanel';
import { ReactFlowProvider } from 'reactflow';
import { EvalDashboard } from './components/evals/EvalDashboard';
import { ObservabilityPanel } from './components/observability/ObservabilityPanel';
import { TrustSettings } from './components/TrustSettings';
import { SettingsPanel } from './components/SettingsPanel';
import { MenuBar } from './components/MenuBar';
import { OrchestratorChat } from './components/OrchestratorChat';
import { WelcomeScreen } from './components/WelcomeScreen';
import { CommandPalette } from './components/Shell/CommandPalette';
import { useToast } from './components/Toast';
import { ProfilePanel } from './components/ProfilePanel';
import { useProfile } from './hooks/useProfile';
import { Panel as ResizePanel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';

interface SessionUser {
    email?: string;
    displayName?: string;
    plan?: string;
    firebaseUser?: boolean;
}

export default function App() {
    const [authenticated, setAuthenticated] = useState<boolean | null>(null);
    const [bootState, setBootState] = useState<'checking' | 'ready' | 'offline'>('checking');
    const [bootError, setBootError] = useState<string | null>(null);
    const [status, setStatus] = useState<UiStatusResponse | null>(null);
    const [activeTab, setActiveTab] = useState<SidebarTab>('graph');
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [graphNodeCount, setGraphNodeCount] = useState(-1);
    const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
    const [isChatCollapsed, setIsChatCollapsed] = useState(false);
    const [isProfileOpen, setIsProfileOpen] = useState(false);
    const [sessionUser, setSessionUser] = useState<SessionUser | null>(null);
    const { currentPlan, loading, createPlan, approvePlan, setCurrentPlan } = usePlanEngine();
    const { addToast } = useToast();
    const {
        profile,
        loading: profileLoading,
        error: profileError,
        unauthorized: profileUnauthorized,
        refetch: refetchProfile,
    } = useProfile(Boolean(authenticated));

    const handleMcpSync = useCallback(async () => {
        try {
            const listRes = await fetch(`${API_BASE}/ops/config/mcp`, { credentials: 'include' });
            if (!listRes.ok) throw new Error(`HTTP ${listRes.status}`);
            const listData = await listRes.json() as { servers?: Array<{ name: string; enabled?: boolean }> };
            const servers = Array.isArray(listData.servers) ? listData.servers : [];
            const candidate = servers.find(s => s.enabled !== false) ?? servers[0];
            if (!candidate?.name) {
                addToast('No hay servidores MCP configurados para sincronizar.', 'info');
                return;
            }

            const syncRes = await fetch(`${API_BASE}/ops/config/mcp/sync`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server_name: candidate.name }),
            });
            if (!syncRes.ok) throw new Error(`HTTP ${syncRes.status}`);

            const payload = await syncRes.json() as { tools_discovered?: number; server?: string };
            addToast(
                `MCP Sync OK (${payload.server || candidate.name}): ${payload.tools_discovered ?? 0} tools`,
                'success'
            );
            setActiveTab('operations');
        } catch (error) {
            addToast('Falló MCP Sync. Revisa configuración de server en Settings.', 'error');
        }
    }, [addToast]);

    const checkSession = useCallback(async () => {
        setBootState('checking');
        setBootError(null);
        try {
            const response = await fetch(`${API_BASE}/auth/check`, { credentials: 'include' });
            if (!response.ok && response.status !== 401) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json().catch(() => ({ authenticated: false }));
            setAuthenticated(data.authenticated === true);
            setSessionUser(
                data.authenticated
                    ? {
                        email: data.email,
                        displayName: data.displayName,
                        plan: data.plan,
                        firebaseUser: data.firebaseUser,
                    }
                    : null,
            );
            setBootState('ready');
        } catch {
            setBootError('No se pudo conectar con GIMO backend.');
            setBootState('offline');
        }
    }, []);

    // Check session on mount
    useEffect(() => {
        checkSession();
    }, [checkSession]);

    useEffect(() => {
        if (!authenticated) return;
        const fetchStatus = async () => {
            try {
                const response = await fetch(`${API_BASE}/ui/status`, {
                    credentials: 'include',
                });
                if (response.status === 401) { setAuthenticated(false); return; }
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                setStatus(data);
                setBootState('ready');
                setBootError(null);
            } catch (error) {
                addToast('No hay conexión con el backend.', 'error');
                setBootState('offline');
                setBootError('No hay conexión con el backend.');
            }
        };
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, [authenticated]);

    const handleNodeSelect = (nodeId: string | null) => {
        setSelectedNodeId(nodeId);
        if (nodeId) setActiveTab('graph');
    };

    const handleCreatePlan = async (req: PlanCreateRequest) => {
        await createPlan(req);
    };

    const handleApprovePlan = async () => {
        if (currentPlan) {
            await approvePlan(currentPlan.id);
        }
    };

    const handleApprovePlanFromGraph = async (draftId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/approve`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan aprobado exitosamente', 'success');
            setGraphNodeCount(-1); // Force refresh
        } catch (err) {
            addToast('Error al aprobar el plan', 'error');
        }
    };

    const handleRejectPlan = async (draftId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/reject`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            addToast('Plan rechazado', 'info');
            setGraphNodeCount(0); // Clear graph
        } catch (err) {
            addToast('Error al rechazar el plan', 'error');
        }
    };

    const openGlobalPlanBuilder = () => setActiveTab('plans');

    const handleSelectView = (tab: SidebarTab) => {
        setActiveTab(tab);
        if (tab !== 'graph') setSelectedNodeId(null);
    };

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                setIsCommandPaletteOpen(true);
            }
        };
        globalThis.addEventListener('keydown', onKeyDown);
        return () => globalThis.removeEventListener('keydown', onKeyDown);
    }, []);

    useEffect(() => {
        if (!authenticated || activeTab !== 'graph' || graphNodeCount !== 0) return;

        const refreshGraphCount = async () => {
            try {
                const response = await fetch(`${API_BASE}/ui/graph`, { credentials: 'include' });
                if (!response.ok) return;
                const payload = await response.json();
                const count = Array.isArray(payload?.nodes) ? payload.nodes.length : 0;
                setGraphNodeCount(count);
            } catch {
                // Silent: welcome screen remains visible on errors
            }
        };

        const interval = globalThis.setInterval(refreshGraphCount, 5000);
        return () => globalThis.clearInterval(interval);
    }, [authenticated, activeTab, graphNodeCount]);

    const handleLogout = useCallback(async () => {
        try {
            await fetch(`${API_BASE}/auth/logout`, {
                method: 'POST',
                credentials: 'include',
            });
        } catch {
            // Ignore network errors on logout; local session state still resets.
        } finally {
            setIsProfileOpen(false);
            setSessionUser(null);
            setAuthenticated(false);
        }
    }, []);

    useEffect(() => {
        if (!authenticated || !profileUnauthorized) return;
        addToast('Sesión expirada. Vuelve a iniciar sesión.', 'info');
        void handleLogout();
    }, [authenticated, profileUnauthorized, addToast, handleLogout]);

    const handleCommandAction = (actionId: string) => {
        switch (actionId) {
            case 'new_plan':
                setActiveTab('plans');
                break;
            case 'open_draft_modal':
                setActiveTab('plans');
                break;
            case 'goto_graph':
                setActiveTab('graph');
                break;
            case 'goto_plans':
                setActiveTab('plans');
                break;
            case 'goto_evals':
                setActiveTab('evals');
                break;
            case 'goto_metrics':
                setActiveTab('metrics');
                break;
            case 'goto_security':
                setActiveTab('security');
                break;
            case 'goto_operations':
                setActiveTab('operations');
                break;
            case 'goto_settings':
                setActiveTab('settings');
                break;
            case 'goto_mastery':
                setActiveTab('mastery');
                break;
            case 'search_repo':
                setActiveTab('operations');
                break;
            case 'mcp_sync':
                void handleMcpSync();
                break;
            case 'view_runs':
                setActiveTab('operations');
                break;
            case 'view_plan':
                setActiveTab('plans');
                break;
            default:
                break;
        }
    };

    const renderMainContent = () => {
        switch (activeTab) {
            case 'graph':
                return (
                    <ReactFlowProvider>
                        {graphNodeCount === 0 ? (
                            <WelcomeScreen
                                onNewPlan={openGlobalPlanBuilder}
                                onConnectProvider={() => setActiveTab('settings')}
                                onOpenRepo={() => setActiveTab('operations')}
                                onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
                            />
                        ) : (
                            <div className="h-full flex flex-col min-h-0 relative">
                                <PanelGroup orientation="vertical">
                                    <ResizePanel
                                        defaultSize={60}
                                        minSize={20}
                                        className="min-h-0 overflow-hidden relative"
                                    >
                                        <GraphCanvas
                                            onNodeSelect={handleNodeSelect}
                                            selectedNodeId={selectedNodeId}
                                            onNodeCountChange={setGraphNodeCount}
                                            onApprovePlan={handleApprovePlanFromGraph}
                                            onRejectPlan={handleRejectPlan}
                                            onEditPlan={openGlobalPlanBuilder}
                                            planLoading={loading}
                                        />
                                    </ResizePanel>

                                    {!isChatCollapsed && (
                                        <>
                                            <PanelResizeHandle className="h-1 bg-surface-3 hover:bg-accent-primary/50 transition-colors cursor-row-resize flex items-center justify-center">
                                                <div className="w-8 h-0.5 bg-border-primary rounded-full" />
                                            </PanelResizeHandle>
                                            <ResizePanel
                                                defaultSize={40}
                                                minSize={20}
                                                className="relative overflow-hidden bg-surface-0 border-t border-border-primary"
                                            >
                                                <div
                                                    className="absolute top-0 right-8 w-12 h-4 bg-surface-2 border border-border-primary border-t-0 rounded-b-md flex items-center justify-center cursor-pointer hover:bg-surface-3 z-50 group transition-colors"
                                                    onClick={() => setIsChatCollapsed(true)}
                                                    title="Colapsar chat"
                                                >
                                                    <div className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-t-[4px] border-t-text-secondary transition-transform" />
                                                </div>
                                                <OrchestratorChat isCollapsed={false} />
                                            </ResizePanel>
                                        </>
                                    )}
                                </PanelGroup>

                                {isChatCollapsed && (
                                    <div className="h-14 min-h-[56px] border-t border-border-primary relative overflow-hidden bg-surface-0 shrink-0">
                                        <div
                                            className="absolute top-0 right-8 w-12 h-4 bg-surface-2 border border-border-primary border-t-0 rounded-b-md flex items-center justify-center cursor-pointer hover:bg-surface-3 z-50 group transition-colors"
                                            onClick={() => setIsChatCollapsed(false)}
                                            title="Expandir chat"
                                        >
                                            <div className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-t-[4px] border-t-text-secondary transition-transform rotate-180" />
                                        </div>
                                        <OrchestratorChat isCollapsed={true} />
                                    </div>
                                )}

                                <div className={`absolute right-0 top-0 bottom-0 z-40 transition-transform duration-300 ease-in-out ${selectedNodeId ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`}>
                                    <InspectPanel
                                        selectedNodeId={selectedNodeId}
                                        onClose={() => setSelectedNodeId(null)}
                                    />
                                </div>
                            </div>
                        )}
                    </ReactFlowProvider>
                );

            case 'plans':
                return (
                    <PlansPanel
                        currentPlan={currentPlan}
                        loading={loading}
                        onCreatePlan={handleCreatePlan}
                        onApprovePlan={handleApprovePlan}
                        onDiscardPlan={() => setCurrentPlan(null)}
                    />
                );

            case 'evals':
                return <EvalDashboard />;

            case 'metrics':
                return <ObservabilityPanel />;

            case 'security':
                return (
                    <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-surface-0">
                        <div className="max-w-6xl mx-auto">
                            <TrustSettings />
                        </div>
                    </div>
                );

            case 'operations':
                return (
                    <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-surface-0">
                        <MaintenanceIsland />
                    </div>
                );


            case 'settings':
                return (
                    <SettingsPanel onOpenMastery={() => setActiveTab('mastery')} />
                );

            case 'mastery':
                return (
                    <div className="h-full overflow-y-auto custom-scrollbar bg-surface-0">
                        <TokenMastery />
                    </div>
                );
        }
    };

    // Loading state
    if (bootState === 'checking' || authenticated === null) {
        return (
            <div className="min-h-screen bg-surface-3 flex items-center justify-center">
                <div className="w-6 h-6 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (bootState === 'offline') {
        return (
            <div className="min-h-screen bg-surface-0 text-text-primary flex items-center justify-center p-6">
                <div className="w-full max-w-lg rounded-2xl border border-border-primary bg-surface-2 p-8 space-y-5">
                    <div className="flex items-center gap-3 text-accent-warning">
                        <AlertTriangle size={20} />
                        <h1 className="text-lg font-semibold">Backend no disponible</h1>
                    </div>
                    <p className="text-sm text-text-secondary">
                        {bootError || 'No se pudo conectar con los servicios de GIMO.'}
                    </p>
                    <div className="flex gap-3">
                        <button
                            onClick={checkSession}
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-accent-primary hover:bg-accent-primary/85 text-white text-sm font-medium"
                        >
                            <RefreshCw size={14} />
                            Reintentar conexión
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // Not authenticated — show login
    if (!authenticated) {
        return <LoginModal onAuthenticated={() => void checkSession()} />;
    }

    const displayName = profile?.user?.displayName || sessionUser?.displayName || sessionUser?.email || 'Mi Perfil';
    const email = profile?.user?.email || sessionUser?.email;

    return (
        <div className="min-h-screen bg-surface-0 text-text-primary font-sans selection:bg-accent-primary selection:text-white flex flex-col">
            <MenuBar
                status={status}
                onNewPlan={openGlobalPlanBuilder}
                onSelectView={handleSelectView}
                onSelectSettingsView={handleSelectView}
                onRefreshSession={checkSession}
                onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
                onMcpSync={() => void handleMcpSync()}
                userDisplayName={displayName}
                userEmail={email}
                userPhotoUrl={profile?.user?.photoURL}
                onOpenProfile={() => setIsProfileOpen(true)}
            />

            <div className="flex flex-1 overflow-hidden">
                <Sidebar activeTab={activeTab} onTabChange={handleSelectView} />

                <main role="main" className="flex-1 relative overflow-hidden">
                    {renderMainContent()}
                </main>
            </div>

            <footer role="contentinfo" className="h-8 border-t border-border-primary bg-surface-1 flex items-center justify-between px-4 text-[10px] text-text-tertiary uppercase tracking-widest shrink-0">
                <div className="flex items-center gap-4">
                    <span>Gred In Labs</span>
                    <span className="text-border-subtle">|</span>
                    <span>v{status?.version || '1.0.0'}</span>
                </div>
                <div className="font-mono lowercase italic opacity-60 text-text-secondary">
                    {status?.service_status || 'connecting...'}
                </div>
            </footer>

            <CommandPalette
                isOpen={isCommandPaletteOpen}
                onClose={() => setIsCommandPaletteOpen(false)}
                onAction={handleCommandAction}
            />

            <ProfilePanel
                isOpen={isProfileOpen}
                onClose={() => setIsProfileOpen(false)}
                profile={profile}
                loading={profileLoading}
                error={profileError}
                onRefresh={() => void refetchProfile()}
                onLogout={() => void handleLogout()}
            />
        </div>
    );
}
