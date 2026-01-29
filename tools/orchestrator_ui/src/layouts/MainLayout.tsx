import React, { useState } from 'react';
import { useEngine } from '../context/EngineContext';
import { StatusStrip } from '../components/StatusStrip';
import { BackgroundLights } from '../components/BackgroundLights';
import { SplashGate } from '../components/SplashGate';
import { ZenHUD } from '../components/ZenHUD';
import { IconSidebar } from '../components/IconSidebar';

// Main Layout Props
interface MainLayoutProps {
    sidebarContent: React.ReactNode;
    mainContent: React.ReactNode;
    rightPanelContent: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({
    sidebarContent,
    mainContent,
    rightPanelContent
}) => {
    // Local UI State
    const [isZenMode, setIsZenMode] = useState(false);
    const [activeSection, setActiveSection] = useState('brush');

    // Engine Data for StatusStrip
    const { telemetry, panic } = useEngine();

    return (
        <div className="flex flex-col h-screen bg-[#09090b] text-slate-200 overflow-hidden font-sans relative">
            <BackgroundLights active={true} />
            <SplashGate />

            {/* Header Strip */}
            <StatusStrip
                telemetry={telemetry}
                isZenMode={isZenMode}
                setIsZenMode={setIsZenMode}
                panic={panic}
            />

            {/* Main Grid Layout */}
            <div className={`flex-1 flex overflow-hidden relative z-10 transition-all duration-500`}>

                {/* Icon Sidebar (48px) */}
                <div className={`transition-all duration-500 ${isZenMode ? 'w-0 opacity-0 overflow-hidden' : 'w-12'}`}>
                    <IconSidebar
                        activeSection={activeSection}
                        onSectionChange={setActiveSection}
                    />
                </div>

                {/* Control Panel (280px) */}
                <aside
                    className={`
                        flex flex-col relative overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.23,1,0.32,1)]
                        ${isZenMode ? 'w-0 opacity-0' : 'w-72 opacity-100'}
                    `}
                >
                    <div className="flex-1 overflow-y-auto custom-scrollbar m-2 p-4 rounded-2xl bg-white/[0.02] border border-white/5">
                        {sidebarContent}
                    </div>
                </aside>

                {/* Central Viewport (flex-1) */}
                <main className="flex-1 flex flex-col relative z-10 transition-all duration-500 m-2">
                    {/* Zen Header (Optional) */}
                    {isZenMode && (
                        <div className="absolute top-4 left-4 z-50 animate-fade-in">
                            <h1 className="text-2xl font-black tracking-[0.2em] text-white/20 pointer-events-none select-none">ZEN COMMAND</h1>
                        </div>
                    )}

                    {/* Viewport Container */}
                    <div className="flex-1 relative rounded-2xl bg-black/20 border border-white/5 overflow-hidden">
                        {mainContent}
                    </div>

                    {isZenMode && <ZenHUD />}
                </main>

                {/* Right Panel - AI Assistant (320px) */}
                <aside
                    className={`
                        flex flex-col relative overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.23,1,0.32,1)]
                        ${isZenMode ? 'w-0 opacity-0' : 'w-80 opacity-100'}
                    `}
                >
                    <div className="flex-1 overflow-hidden m-2">
                        {rightPanelContent}
                    </div>
                </aside>
            </div>
        </div>
    );
};
