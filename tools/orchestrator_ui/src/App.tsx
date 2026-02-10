import { MaintenanceIsland } from './islands/system/MaintenanceIsland';
import { OpsIsland } from './islands/system/OpsIsland';

export default function App() {
    return (
        <div className="min-h-screen bg-[#000000] font-sans antialiased text-base">
            <div className="max-w-5xl mx-auto px-6 py-12">
                {/* Header */}
                <header className="mb-12 text-center">
                    <h1 className="text-4xl font-semibold text-[#f5f5f7] tracking-tight">
                        Repo Orchestrator
                    </h1>
                    <p className="text-base text-[#86868b] mt-2">
                        Gred In Labs
                    </p>
                </header>

                {/* Main Content */}
                <main className="space-y-8">
                    <div className="bg-[#1c1c1e] rounded-2xl shadow-2xl border border-[#38383a] p-8">
                        <MaintenanceIsland token={import.meta.env.VITE_ORCH_TOKEN} />
                    </div>

                    <div className="bg-[#1c1c1e] rounded-2xl shadow-2xl border border-[#38383a] p-8">
                        <OpsIsland token={import.meta.env.VITE_ORCH_TOKEN} />
                    </div>
                </main>

                {/* Footer */}
                <footer className="mt-8 text-center text-sm text-[#86868b]">
                    v1.0.0
                </footer>
            </div>
        </div>
    );
}
