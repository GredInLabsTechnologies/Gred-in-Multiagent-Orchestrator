import React, { useState, useEffect } from 'react';
import { MessageSquare, Terminal, Activity, Maximize2, Minimize2, Settings2 } from 'lucide-react';
import { OrchestratorChat } from './OrchestratorChat';
import { OpsTerminal } from './OpsTerminal';
import { OpsFlow } from './OpsFlow';
import { API_BASE, OpsConfig } from '../types';

export const ChatTerminalLayout: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'chat' | 'terminal' | 'flow'>('chat');
    const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>(undefined);
    const [isSplit, setIsSplit] = useState(false);
    const [config, setConfig] = useState<OpsConfig | null>(null);

    useEffect(() => {
        const fetchConfig = async () => {
            try {
                const resp = await fetch(`${API_BASE}/ops/config`, { credentials: 'include' });
                if (resp.ok) {
                    const data = await resp.json();
                    setConfig(data);
                    // If flow is disabled but active, switch to chat
                    if (data.ui_show_ids_events === false && activeTab === 'flow') {
                        setActiveTab('chat');
                    }
                }
            } catch (err) {
                console.error('Failed to fetch ops config:', err);
            }
        };
        fetchConfig();
    }, [activeTab]);

    const renderSecondaryTab = () => {
        if (!isSplit) return null;
        const secondaryTab = activeTab === 'chat' ? 'terminal' : 'chat';

        return (
            <div className="flex-1 flex flex-col min-w-0 border-l border-white/[0.04] bg-surface-1">
                <div className="h-10 px-4 flex items-center justify-between border-b border-white/[0.04] bg-surface-2/50">
                    <div className="flex items-center gap-2">
                        {secondaryTab === 'chat' ? <MessageSquare size={14} /> : <Terminal size={14} />}
                        <span className="text-[10px] uppercase tracking-widest font-bold text-text-secondary">
                            {secondaryTab === 'chat' ? 'Chat' : 'Terminal'} (Vista Dividida)
                        </span>
                    </div>
                </div>
                <div className="flex-1 min-h-0">
                    {secondaryTab === 'chat' ? (
                        <OrchestratorChat onViewInFlow={(id) => {
                            setSelectedAgentId(id);
                            setActiveTab('flow');
                        }} />
                    ) : (
                        <OpsTerminal />
                    )}
                </div>
            </div>
        );
    };

    const renderActiveContent = () => {
        switch (activeTab) {
            case 'chat':
                return (
                    <OrchestratorChat onViewInFlow={(id) => {
                        setSelectedAgentId(id);
                        setActiveTab('flow');
                    }} />
                );
            case 'terminal':
                return <OpsTerminal />;
            case 'flow':
                return <OpsFlow agentId={selectedAgentId} />;
            default:
                return (
                    <OrchestratorChat onViewInFlow={(id) => {
                        setSelectedAgentId(id);
                        setActiveTab('flow');
                    }} />
                );
        }
    };

    return (
        <div className="flex flex-col h-full bg-surface-1 overflow-hidden">
            {/* Header / Tabs */}
            <div className="shrink-0 h-10 px-2 flex items-center justify-between border-b border-white/[0.04] bg-surface-2/80 backdrop-blur-md z-10">
                <div className="flex items-center gap-1">
                    <button
                        onClick={() => setActiveTab('chat')}
                        className={`px-4 h-8 flex items-center gap-2 rounded-md transition-all text-[11px] font-medium ${activeTab === 'chat'
                            ? 'bg-white/[0.06] text-text-primary shadow-sm'
                            : 'text-text-tertiary hover:text-text-secondary hover:bg-white/[0.02]'
                            }`}
                    >
                        <MessageSquare size={14} className={activeTab === 'chat' ? 'text-accent-primary' : ''} />
                        Chat
                    </button>
                    <button
                        onClick={() => setActiveTab('terminal')}
                        className={`px-4 h-8 flex items-center gap-2 rounded-md transition-all text-[11px] font-medium ${activeTab === 'terminal'
                            ? 'bg-white/[0.06] text-text-primary shadow-sm'
                            : 'text-text-tertiary hover:text-text-secondary hover:bg-white/[0.02]'
                            }`}
                    >
                        <Terminal size={14} className={activeTab === 'terminal' ? 'text-accent-primary' : ''} />
                        Terminal
                    </button>
                    {config?.ui_show_ids_events !== false && (
                        <button
                            onClick={() => setActiveTab('flow')}
                            className={`px-4 h-8 flex items-center gap-2 rounded-md transition-all text-[11px] font-medium ${activeTab === 'flow'
                                ? 'bg-white/[0.06] text-text-primary shadow-sm'
                                : 'text-text-tertiary hover:text-text-secondary hover:bg-white/[0.02]'
                                }`}
                        >
                            <Activity size={14} className={activeTab === 'flow' ? 'text-accent-primary' : ''} />
                            Flujo
                        </button>
                    )}
                </div>

                <div className="flex items-center gap-2 px-2">
                    <button
                        onClick={() => setIsSplit(!isSplit)}
                        className={`p-1.5 rounded-md transition-all ${isSplit ? 'bg-accent-primary/10 text-accent-primary' : 'text-text-tertiary hover:text-text-secondary'
                            }`}
                        title={isSplit ? 'Cerrar vista dividida' : 'Vista dividida (Chat + Terminal)'}
                    >
                        {isSplit ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                    </button>
                    <div className="w-px h-4 bg-white/[0.06] mx-1" />
                    <button className="p-1.5 text-text-tertiary hover:text-text-secondary transition-all">
                        <Settings2 size={16} />
                    </button>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex min-h-0 relative">
                <div className="flex-1 min-w-0 flex flex-col relative">
                    {renderActiveContent()}
                </div>
                {renderSecondaryTab()}
            </div>
        </div>
    );
};
