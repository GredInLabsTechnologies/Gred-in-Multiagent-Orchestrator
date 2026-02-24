import React from 'react';
import { FolderOpen, Keyboard, PlugZap, Sparkles } from 'lucide-react';

interface WelcomeScreenProps {
    onNewPlan: () => void;
    onConnectProvider: () => void;
    onOpenRepo: () => void;
    onOpenCommandPalette: () => void;
}

const WelcomeButton = ({ icon, title, description, onClick }: { icon: React.ReactNode, title: string, description: string, onClick: () => void }) => (
    <button
        onClick={onClick}
        className="group relative h-28 rounded-2xl border border-[#2c2c2e] bg-[#141414]/50 p-4 text-left transition-all hover:border-[#0a84ff]/50 hover:bg-[#0a84ff]/5 shadow-sm hover:shadow-blue-500/10"
    >
        <div className="mb-3 transition-transform group-hover:scale-110 group-hover:-rotate-3">
            {icon}
        </div>
        <div className="text-sm font-bold text-[#f5f5f7] tracking-tight">{title}</div>
        <div className="mt-1 text-[11px] leading-tight text-[#86868b] group-hover:text-[#f5f5f7]/70 transition-colors">
            {description}
        </div>
    </button>
);

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
    onNewPlan,
    onConnectProvider,
    onOpenRepo,
    onOpenCommandPalette,
}) => {
    return (
        <section className="h-full w-full bg-[#0a0a0a] flex items-center justify-center p-6">
            <div className="w-full max-w-3xl rounded-3xl border border-[#2c2c2e] bg-[#111113] p-10 md:p-12 shadow-2xl relative overflow-hidden">
                {/* Decorative background element */}
                <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2" />

                <div className="relative">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#2c2c2e] bg-[#1c1c1e] text-[#0a84ff] text-[10px] uppercase font-black tracking-widest mb-6 animate-in fade-in slide-in-from-bottom-2 duration-1000">
                        <Sparkles size={12} className="animate-pulse" /> GIMO Orquestador
                    </div>

                    <h1 className="text-3xl md:text-4xl font-black text-[#f5f5f7] tracking-tighter mb-4">
                        Bienvenido al Sistema
                    </h1>

                    <p className="text-sm text-[#86868b] max-w-xl leading-relaxed mb-10">
                        El grafo de orquestación está inactivo. Inicia una nueva secuencia de planificación,
                        conecta tus proveedores de IA o explora el repositorio local para comenzar.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <WelcomeButton
                            icon={<Sparkles className="w-5 h-5 text-blue-400" />}
                            title="Nuevo Plan"
                            description="Inicia un flujo de trabajo guiado para crear una secuencia de tareas."
                            onClick={onNewPlan}
                        />
                        <WelcomeButton
                            icon={<PlugZap className="w-5 h-5 text-[#ff9f0a]" />}
                            title="Proveedores"
                            description="Configura tus modelos LLM y claves de API para la inferencia."
                            onClick={onConnectProvider}
                        />
                        <WelcomeButton
                            icon={<FolderOpen className="w-5 h-5 text-emerald-400" />}
                            title="Repositorio"
                            description="Selecciona y audita el directorio de trabajo actual del sistema."
                            onClick={onOpenRepo}
                        />
                        <WelcomeButton
                            icon={<Keyboard className="w-5 h-5 text-zinc-400" />}
                            title="Comandos"
                            description="Abre la paleta de comandos para acceso rápido a utilidades."
                            onClick={onOpenCommandPalette}
                        />
                    </div>

                    <button
                        onClick={onOpenCommandPalette}
                        className="mt-10 inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-[#0a84ff]/70 hover:text-[#0a84ff] transition-colors"
                    >
                        <Keyboard size={14} /> Presiona <span className="bg-[#1c1c1e] px-1.5 py-0.5 rounded border border-[#2c2c2e] mx-1 text-white">Ctrl+K</span> para buscar
                    </button>
                </div>
            </div>
        </section>
    );
};
