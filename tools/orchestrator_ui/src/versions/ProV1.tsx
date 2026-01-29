import React, { useState } from 'react';
import { BackgroundLights } from '../components/BackgroundLights';
import { MockStatusStrip } from './components/MockStatusStrip';
import { MockSidebar } from './components/MockSidebar';
import { MockChatArea } from './components/MockChatArea';
import { MockOutputPanel } from './components/MockOutputPanel';

export const ProV1: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'creative' | 'system' | 'json'>('creative');
    const [isZenMode, setIsZenMode] = useState(false);

    return (
        <div className="flex flex-col h-screen bg-[#09090b] text-slate-200 overflow-hidden font-sans relative">
            <BackgroundLights active={true} />

            <MockStatusStrip
                isZenMode={isZenMode}
                setIsZenMode={setIsZenMode}
            />

            <div className="flex flex-1 overflow-hidden relative z-10 p-2">
                {/* Left Sidebar */}
                {!isZenMode && (
                    <aside className="w-80 sidebar-panel flex flex-col z-20 m-2 rounded-[2rem] relative overflow-hidden bg-white/5 border border-white/5">
                        <MockSidebar activeTab={activeTab} setActiveTab={setActiveTab} />
                    </aside>
                )}

                {/* Main Viewport */}
                <main className="flex-1 flex flex-col relative z-10">
                    <MockChatArea />
                </main>

                {/* Right Sidebar */}
                {!isZenMode && (
                    <aside className="w-96 sidebar-panel flex flex-col z-20 m-2 rounded-[2rem] relative overflow-hidden bg-white/5 border border-white/5">
                        <MockOutputPanel />
                    </aside>
                )}
            </div>
        </div>
    );
};
