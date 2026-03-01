import { ReactFlowProvider } from 'reactflow';
import { Panel as ResizePanel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { GraphCanvas } from '../components/GraphCanvas';
import { InspectPanel } from '../components/InspectPanel';
import { OrchestratorChat } from '../components/OrchestratorChat';
import { WelcomeScreen } from '../components/WelcomeScreen';
import { useAppStore } from '../stores/appStore';

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
    const selectedNodeId = useAppStore((s) => s.selectedNodeId);
    const selectNode = useAppStore((s) => s.selectNode);
    const isChatCollapsed = useAppStore((s) => s.isChatCollapsed);
    const toggleChat = useAppStore((s) => s.toggleChat);
    const setActiveTab = useAppStore((s) => s.setActiveTab);
    const setActivePlanIdFromChat = useAppStore((s) => s.setActivePlanIdFromChat);

    return (
        <ReactFlowProvider>
            {graphNodeCount === 0 ? (
                <WelcomeScreen
                    onNewPlan={onNewPlan}
                    onConnectProvider={() => setActiveTab('settings')}
                    onOpenRepo={() => setActiveTab('operations')}
                    onOpenCommandPalette={() => useAppStore.getState().toggleCommandPalette(true)}
                    providerConnected={providerHealth.connected}
                    providerName={providerHealth.providerName}
                    providerModel={providerHealth.model}
                />
            ) : (
                <div className="h-full flex flex-col min-h-0 relative">
                    <PanelGroup orientation="vertical">
                        <ResizePanel defaultSize={60} minSize={20} className="min-h-0 overflow-hidden relative">
                            <GraphCanvas
                                onNodeSelect={(nodeId) => selectNode(nodeId)}
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
                                    <OrchestratorChat
                                        isCollapsed={false}
                                        providerConnected={providerHealth.connected}
                                        onPlanGenerated={(planId) => setActivePlanIdFromChat(planId)}
                                        onNavigateToSettings={() => setActiveTab('settings')}
                                    />
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
                            <OrchestratorChat
                                isCollapsed={true}
                                providerConnected={providerHealth.connected}
                                onPlanGenerated={(planId) => setActivePlanIdFromChat(planId)}
                                onNavigateToSettings={() => setActiveTab('settings')}
                            />
                        </div>
                    )}

                    <div className={`absolute right-0 top-0 bottom-0 z-40 transition-transform duration-300 ease-in-out ${selectedNodeId ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`}>
                        <InspectPanel
                            selectedNodeId={selectedNodeId}
                            onClose={() => selectNode(null)}
                        />
                    </div>
                </div>
            )}
        </ReactFlowProvider>
    );
}
