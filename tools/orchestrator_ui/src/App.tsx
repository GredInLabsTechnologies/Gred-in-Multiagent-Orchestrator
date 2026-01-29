import { useState, useEffect } from 'react';
import { EngineProvider, useEngine } from './context/EngineContext';
import { MainLayout } from './layouts/MainLayout';
import { ProV1 } from './versions/ProV1';

// Islands
import { ControlIsland } from './islands/ControlIsland';
import { AIAssistantPanel } from './islands/AIAssistantPanel';
import { OutputIsland } from './islands/OutputIsland';

import { API_BASE, Message } from './types';

import { Settings, FlaskConical } from 'lucide-react';
import { TheVault } from './components/TheVault';
import { MaintenanceIsland } from './islands/system/MaintenanceIsland';

// Inner Component to consume Context
function OrchestratorApp() {
    const [labMode, setLabMode] = useState(false);
    const {
        telemetry, activeJob,
        history, workflows, availableBackends,
        startEngine, stopEngine,
        lastPing,
        isAgentThinking
    } = useEngine();



    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isProcessing, setIsProcessing] = useState(false);
    const [rightTab, setRightTab] = useState<'output' | 'runs'>('output');


    // Engine State 
    const [activeWorkflow, setActiveWorkflow] = useState('repo_analyzer_v1');
    const [activeBackend, setActiveBackend] = useState('flux_gguf');
    const [isVaultOpen, setIsVaultOpen] = useState(false);

    // Sync Active Job from Context
    useEffect(() => {
        if (activeJob) {
            // Keep for potential job tracking UI updates
        }
    }, [activeJob]);




    // --- Handlers ---
    const handleSend = async () => {
        if (!input.trim() || isProcessing) return;
        const currentInput = input;
        setIsProcessing(true);
        setInput('');

        // Basic Chat Echo
        setMessages(prev => [...prev, { id: Date.now().toString(), type: 'user', text: currentInput, timestamp: new Date() }]);

        try {
            // Unify Flow: Parallel execution of Chat (Conversational) and Copilot (Intent & Plan)
            const [chatResp, intentResp] = await Promise.all([
                fetch(`${API_BASE}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: currentInput, history: [] })
                }),
                fetch(`${API_BASE}/copilot/intent`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ intent: currentInput, history: [] })
                })
            ]);

            const chatResult = await chatResp.json();
            const intentResult = await intentResp.json();

            // 1. Show Chat Response (Conversational)
            if (chatResult.text) {
                setMessages(prev => [...prev, { id: Date.now().toString(), type: 'ai', text: chatResult.text, timestamp: new Date() }]);
            }

            // 2. Handle Action (Orchestration)
            if (intentResult.action === 'orchestrate' && intentResult.job) {
                const job = intentResult.job;

                const genResp = await fetch(`${API_BASE}/generate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        backend: activeBackend,
                        workflow: activeWorkflow,
                        prompt: job.user_intent
                    })
                });


                const genResult = await genResp.json();
                setMessages(prev => [...prev, {
                    id: Date.now().toString() + '_gen',
                    type: 'ai',
                    text: `⚙️ Executing Orchestration... (Job ID: ${genResult.prompt_id})`,
                    timestamp: new Date()
                }]);
            }
        } catch (err) {

            setMessages(prev => [...prev, { id: Date.now().toString(), type: 'ai', text: `⚠️ Error: ${err}`, timestamp: new Date() }]);
        } finally { setIsProcessing(false); }
    };

    // Note: handleAnalyze temporarily disabled - will be re-enabled when AI panel supports it

    // --- Composition ---
    const SidebarContent = (
        <>
            <div className="flex items-center space-x-3 z-10 relative mb-6">
                <img src="/logo.png" alt="GRED Logo" className="w-10 h-10 object-contain drop-shadow-[0_0_15px_rgba(34,211,238,0.5)]" />
                <div>
                    <h1 className="text-lg font-bold tracking-tighter text-white/90 leading-none">GRED <span className="text-accent-primary font-light">IN LABS</span></h1>
                    <p className="text-[9px] text-slate-500 font-bold tracking-[0.15em] mt-0.5">ASSETS ENGINE | GIOS</p>
                </div>
            </div>

            <ControlIsland
                workflows={workflows}
                activeWorkflow={activeWorkflow}
                setActiveWorkflow={setActiveWorkflow}
                telemetry={telemetry}
                setIsVaultOpen={setIsVaultOpen}
                availableBackends={availableBackends}
                activeBackend={activeBackend}
                setActiveBackend={setActiveBackend}
                startEngine={startEngine}
                stopEngine={stopEngine}
            />

            <MaintenanceIsland />

            <div className="pt-4 border-t border-white/5 z-10 mt-4">
                <div className="flex items-center py-2 rounded-xl hover:bg-white/5 cursor-pointer transition-all">
                    <div className="w-9 h-9 rounded-full bg-slate-800 flex items-center justify-center overflow-hidden">
                        <span className="text-xs font-bold text-white">AD</span>
                    </div>
                    <div className="ml-3 flex-1">
                        <p className="text-sm font-bold text-white">Admin</p>
                        <p className="text-[10px] text-slate-500">Ping: {lastPing}ms</p>
                    </div>
                    <button onClick={() => console.log("Settings Open")} className="p-2 hover:bg-white/10 rounded-full transition-colors group">
                        <Settings className="w-4 h-4 text-slate-400 group-hover:text-accent-primary transition-colors" />
                    </button>
                </div>
            </div>
        </>
    );

    if (labMode) {
        return (
            <div className="relative h-screen bg-black">
                <ProV1 />
                <button
                    onClick={() => setLabMode(false)}
                    className="fixed bottom-6 right-6 z-[100] bg-accent-primary text-white p-4 rounded-full shadow-2xl hover:scale-110 active:scale-95 transition-all flex items-center space-x-2"
                >
                    <FlaskConical className="w-5 h-5" />
                    <span className="text-xs font-bold uppercase tracking-widest px-2">Exit Lab</span>
                </button>
            </div>
        );
    }

    return (
        <div className="relative h-screen bg-black">
            <MainLayout
                sidebarContent={SidebarContent}
                mainContent={
                    <OutputIsland
                        rightTab={rightTab}
                        setRightTab={setRightTab}
                        history={history}
                        messages={messages}
                        setMessages={setMessages}
                        isVaultOpen={isVaultOpen}
                        setIsVaultOpen={setIsVaultOpen}
                        handleAnalyze={() => { }}
                        isAnalyzing={false}
                    />
                }
                rightPanelContent={
                    <AIAssistantPanel
                        messages={messages}
                        input={input}
                        setInput={setInput}
                        handleSend={handleSend}
                        isProcessing={isProcessing}
                        isAgentThinking={isAgentThinking}
                    />
                }

            />

            {
                isVaultOpen && (
                    <TheVault
                        assets={history}
                        apiBase={API_BASE}
                        onClose={() => setIsVaultOpen(false)}
                        onSelectAsset={(asset: string) => {
                            console.log("Selected asset:", asset);
                            setIsVaultOpen(false);
                        }}
                    />
                )
            }


            <button
                onClick={() => setLabMode(true)}
                className="fixed bottom-6 right-6 z-[100] bg-white/5 border border-white/10 text-white/50 p-4 rounded-full shadow-2xl hover:bg-accent-primary hover:text-white transition-all flex items-center space-x-2"
            >
                <FlaskConical className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-widest px-2">Enter Lab</span>
            </button>
        </div>
    );
}


export default function App() {
    return (
        <EngineProvider>
            <OrchestratorApp />
        </EngineProvider>
    );
}
