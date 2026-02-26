import { Bot, User, Cpu, Code, FileText, AlertCircle, Wrench } from 'lucide-react';

interface GimoItem {
    id: string;
    type: 'text' | 'tool_call' | 'tool_result' | 'diff' | 'thought' | 'error';
    content: string;
    status: 'started' | 'delta' | 'completed' | 'error';
    metadata?: any;
}

interface GimoTurn {
    id: string;
    agent_id: string;
    items: GimoItem[];
    created_at: string;
}

interface TurnItemProps {
    turn: GimoTurn;
}

export const TurnItem: React.FC<TurnItemProps> = ({ turn }) => {
    const isOrchestrator = turn.agent_id.toLowerCase().includes('orchestrator');

    const renderItemIcon = (type: string) => {
        switch (type) {
            case 'tool_call': return <Cpu size={14} className="text-blue-400" />;
            case 'tool_result': return <Wrench size={14} className="text-green-400" />;
            case 'diff': return <Code size={14} className="text-purple-400" />;
            case 'thought': return <Bot size={14} className="text-gray-400" />;
            case 'error': return <AlertCircle size={14} className="text-red-400" />;
            default: return <FileText size={14} className="text-gray-400" />;
        }
    };

    return (
        <div className={`mb-6 flex flex-col ${isOrchestrator ? 'items-start' : 'items-end'}`}>
            <div className={`flex items-center gap-2 mb-2 ${isOrchestrator ? 'flex-row' : 'flex-row-reverse'}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center ${isOrchestrator ? 'bg-blue-600' : 'bg-green-600'}`}>
                    {isOrchestrator ? <Bot size={18} /> : <User size={18} />}
                </div>
                <div className="flex flex-col">
                    <span className="text-[11px] font-bold text-text-primary">{turn.agent_id}</span>
                    <span className="text-[9px] text-text-secondary uppercase">{new Date(turn.created_at).toLocaleTimeString()}</span>
                </div>
            </div>

            <div className={`max-w-[85%] space-y-3 ${isOrchestrator ? 'pl-10' : 'pr-10'}`}>
                {turn.items.map((item) => (
                    <div key={item.id} className="bg-surface-2 border border-border-primary rounded-2xl overflow-hidden shadow-xl">
                        <div className="px-3 py-1.5 bg-surface-3/50 border-b border-border-subtle flex items-center gap-2 justify-between">
                            <div className="flex items-center gap-2">
                                {renderItemIcon(item.type)}
                                <span className="text-[10px] font-medium uppercase tracking-wider text-text-secondary">{item.type}</span>
                            </div>
                            {item.status !== 'completed' && (
                                <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 bg-accent-primary rounded-full animate-status-pulse" />
                                    <span className="text-[9px] text-accent-primary font-bold uppercase">{item.status}</span>
                                </div>
                            )}
                        </div>
                        <div className="p-4 text-[13px] leading-relaxed text-text-primary whitespace-pre-wrap font-mono">
                            {item.content}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
