import { useEffect, useState } from 'react';
import { ReactFlowProvider } from 'reactflow';
import { Panel as ResizePanel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { GraphCanvas } from '../components/GraphCanvas';
import { InspectPanel } from '../components/InspectPanel';
import { ChatTerminalLayout } from '../components/ChatTerminalLayout';
import { WelcomeScreen } from '../components/WelcomeScreen';
import { useAppStore } from '../stores/appStore';
import { API_BASE } from '../types';

interface GraphViewProps {
    providerHealth: { connected: boolean; providerName?: string; model?: string };
    graphNodeCount: number;
    onGraphNodeCountChange: (n: number) => void;
    onApprovePlan: (draftId: string) => Promise<void>;
    onRejectPlan: (draftId: string) => Promise<void>;
    onNewPlan: () => void;
    activePlanIdFromChat: string | null;
}

export default function GraphView({
    providerHealth,
    graphNodeCount,
    onGraphNodeCountChange,
    onApprovePlan,
    onRejectPlan,
    onNewPlan,
    activePlanIdFromChat,
}: GraphViewProps) {
    const WELCOME_COOKIE = 'gimo_welcome_dismissed';

    const selectedNodeId = useAppStore((s) => s.selectedNodeId);
    const selectNode = useAppStore((s) => s.selectNode);
    const isChatCollapsed = useAppStore((s) => s.isChatCollapsed);
    const toggleChat = useAppStore((s) => s.toggleChat);
    const navigate = useAppStore((s) => s.navigate);
    const [showWelcome, setShowWelcome] = useState(true);
    const [repoConnected, setRepoConnected] = useState(false);
    const [repoPath, setRepoPath] = useState<string>('');
    const [hasActivity, setHasActivity] = useState(false);

    useEffect(() => {
        try {
            const hasDismissed = document.cookie
                .split(';')
                .map((c) => c.trim())
                .some((c) => c.startsWith(`${WELCOME_COOKIE}=true`));
            setShowWelcome(!hasDismissed);
        } catch {
            setShowWelcome(true);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;

        const loadOnboardingState = async () => {
            try {
                const [repoRes, draftsRes, runsRes] = await Promise.all([
                    fetch(`${API_BASE}/ui/repos/active`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ops/drafts`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ops/runs`, { credentials: 'include' }),
                ]);

                if (cancelled) return;

                if (repoRes.ok) {
                    const repoData = await repoRes.json();
                    const active = String(repoData?.active_repo || '').trim();
                    setRepoConnected(Boolean(active));
                    setRepoPath(active);
                }

                let draftsCount = 0;
                let runsCount = 0;

                if (draftsRes.ok) {
                    const drafts = await draftsRes.json();
                    draftsCount = Array.isArray(drafts) ? drafts.length : 0;
                }

                if (runsRes.ok) {
                    const runs = await runsRes.json();
                    runsCount = Array.isArray(runs) ? runs.length : 0;
                }

                setHasActivity(draftsCount > 0 || runsCount > 0);
            } catch {
                // non-blocking onboarding hints
            }
        };

        void loadOnboardingState();
        const interval = setInterval(loadOnboardingState, 10000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);

    const handleDismissWelcome = (neverShowAgain: boolean) => {
        if (neverShowAgain) {
            const maxAge = 60 * 60 * 24 * 365;
            document.cookie = `${WELCOME_COOKIE}=true; path=/; max-age=${maxAge}; samesite=lax`;
        }
        setShowWelcome(false);
    };

    return (
        <ReactFlowProvider>
            <div className="h-full flex flex-col min-h-0 relative">
                {showWelcome && (
                    <div className="absolute top-4 left-4 right-4 z-50 max-w-4xl mx-auto">
                        <WelcomeScreen
                            onNewPlan={onNewPlan}
                            onConnectProvider={() => navigate('connections')}
                            onOpenRepo={() => navigate('operations')}
                            onOpenCommandPalette={() => useAppStore.getState().toggleCommandPalette(true)}
                            onDismiss={handleDismissWelcome}
                            providerConnected={providerHealth.connected}
                            providerName={providerHealth.providerName}
                            providerModel={providerHealth.model}
                            repoConnected={repoConnected}
                            repoPath={repoPath}
                            hasActivity={hasActivity || graphNodeCount > 0}
                        />
                    </div>
                )}

                <PanelGroup orientation="vertical">
                    <ResizePanel defaultSize={60} minSize={20} className="min-h-0 overflow-hidden relative">
                        <GraphCanvas
                            onNodeSelect={selectNode}
                            selectedNodeId={selectedNodeId}
                            onNodeCountChange={onGraphNodeCountChange}
                            onApprovePlan={onApprovePlan}
                            onRejectPlan={onRejectPlan}
                            onEditPlan={onNewPlan}
                            planLoading={false}
                            activePlanIdFromChat={activePlanIdFromChat}
                        />
                    </ResizePanel>

                    {!isChatCollapsed && (
                        <>
                            <PanelResizeHandle className="h-1 bg-surface-3 hover:bg-accent-primary/50 transition-colors cursor-row-resize flex items-center justify-center">
                                <div className="w-8 h-0.5 bg-border-primary rounded-full" />
                            </PanelResizeHandle>
                            <ResizePanel defaultSize={40} minSize={20} className="relative overflow-hidden bg-surface-0 border-t border-border-primary">
                                <div
                                    className="absolute top-0 right-8 w-12 h-4 bg-surface-2 border border-border-primary border-t-0 rounded-b-md flex items-center justify-center cursor-pointer hover:bg-surface-3 z-50 group transition-colors"
                                    onClick={() => toggleChat(true)}
                                    title="Colapsar chat"
                                >
                                    <div className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-t-[4px] border-t-text-secondary transition-transform" />
                                </div>
                                <ChatTerminalLayout />
                            </ResizePanel>
                        </>
                    )}
                </PanelGroup>

                {isChatCollapsed && (
                    <div className="h-14 min-h-[56px] border-t border-border-primary relative overflow-hidden bg-surface-0 shrink-0">
                        <div
                            className="absolute top-0 right-8 w-12 h-4 bg-surface-2 border border-border-primary border-t-0 rounded-b-md flex items-center justify-center cursor-pointer hover:bg-surface-3 z-50 group transition-colors"
                            onClick={() => toggleChat(false)}
                            title="Expandir chat"
                        >
                            <div className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-t-[4px] border-t-text-secondary transition-transform rotate-180" />
                        </div>
                        <div className="h-full flex items-center px-4 text-[11px] uppercase tracking-wider text-text-secondary">
                            Chat/Terminal colapsado
                        </div>
                    </div>
                )}

                <div className={`absolute right-0 top-0 bottom-0 z-40 transition-transform duration-300 ease-in-out ${selectedNodeId ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`}>
                    <InspectPanel selectedNodeId={selectedNodeId} onClose={() => selectNode(null)} />
                </div>
            </div>
        </ReactFlowProvider>
    );
}