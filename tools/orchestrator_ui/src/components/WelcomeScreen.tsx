import React from 'react';
import { FolderOpen, Keyboard, PlugZap, Sparkles } from 'lucide-react';

interface WelcomeScreenProps {
    onNewPlan: () => void;
    onConnectProvider: () => void;
    onOpenRepo: () => void;
    onOpenCommandPalette: () => void;
    providerConnected?: boolean;
    providerName?: string;
    providerModel?: string;
}

const WelcomeButton = ({ icon, title, description, onClick }: { icon: React.ReactNode, title: string, description: string, onClick: () => void }) => (
    <button
        onClick={onClick}
        className="group relative h-28 rounded-2xl border border-border-primary bg-surface-2/50 p-4 text-left transition-all hover:border-accent-primary/50 hover:bg-accent-primary/5 shadow-sm hover:shadow-[0_0_12px_var(--glow-primary)]"
    >
        <div className="mb-3 transition-transform group-hover:scale-110 group-hover:-rotate-3">
            {icon}
        </div>
        <div className="text-sm font-bold text-text-primary tracking-tight">{title}</div>
        <div className="mt-1 text-[11px] leading-tight text-text-secondary group-hover:text-text-primary/70 transition-colors">
            {description}
        </div>
    </button>
);

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
    onNewPlan,
    onConnectProvider,
    onOpenRepo,
    onOpenCommandPalette,
    providerConnected,
    providerName,
    providerModel,
}) => {
    return (
        <section className="h-full w-full bg-surface-0 flex items-center justify-center p-6">
            <div className="w-full max-w-3xl rounded-3xl border border-border-primary bg-surface-1 p-10 md:p-12 shadow-2xl relative overflow-hidden">
                {/* Decorative background element */}
                <div className="absolute top-0 right-0 w-64 h-64 bg-accent-primary/10 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2" />

                <div className="relative">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-border-primary bg-surface-3 text-accent-primary text-[10px] uppercase font-black tracking-widest mb-6 animate-in fade-in slide-in-from-bottom-2 duration-1000">
                        <Sparkles size={12} className="animate-pulse" /> GIMO Orquestador
                    </div>

                    <h1 className="text-3xl md:text-4xl font-black text-text-primary tracking-tighter mb-4">
                        Bienvenido al Sistema
                    </h1>

                    {providerConnected ? (
                        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-medium mb-6">
                            <span className="w-2 h-2 rounded-full bg-emerald-400" />
                            Conectado a {providerName || 'Provider'} {providerModel ? `/ ${providerModel}` : ''}
                        </div>
                    ) : (
                        <button
                            onClick={onConnectProvider}
                            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 text-xs font-medium mb-6 hover:bg-red-500/20 transition-colors"
                        >
                            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
                            Sin provider configurado — click para configurar
                        </button>
                    )}

                    <p className="text-sm text-text-secondary max-w-xl leading-relaxed mb-10">
                        {providerConnected
                            ? 'El sistema está listo. Crea un nuevo plan desde el chat o en modo edición, conecta dependencias entre nodos y ejecuta.'
                            : 'Configura un provider de IA primero para poder generar y ejecutar planes de orquestación.'}
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <WelcomeButton
                            icon={<Sparkles className="w-5 h-5 text-accent-primary" />}
                            title="Nuevo Plan"
                            description="Inicia un flujo de trabajo guiado para crear una secuencia de tareas."
                            onClick={onNewPlan}
                        />
                        <WelcomeButton
                            icon={<PlugZap className="w-5 h-5 text-accent-warning" />}
                            title="Proveedores"
                            description="Configura tus modelos LLM y claves de API para la inferencia."
                            onClick={onConnectProvider}
                        />
                        <WelcomeButton
                            icon={<FolderOpen className="w-5 h-5 text-accent-trust" />}
                            title="Repositorio"
                            description="Selecciona y audita el directorio de trabajo actual del sistema."
                            onClick={onOpenRepo}
                        />
                        <WelcomeButton
                            icon={<Keyboard className="w-5 h-5 text-text-secondary" />}
                            title="Comandos"
                            description="Abre la paleta de comandos para acceso rápido a utilidades."
                            onClick={onOpenCommandPalette}
                        />
                    </div>

                    <button
                        onClick={onOpenCommandPalette}
                        className="mt-10 inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-accent-primary/70 hover:text-accent-primary transition-colors"
                    >
                        <Keyboard size={14} /> Presiona <span className="bg-surface-3 px-1.5 py-0.5 rounded border border-border-primary mx-1 text-text-primary">Ctrl+K</span> para buscar
                    </button>
                </div>
            </div>
        </section>
    );
};
