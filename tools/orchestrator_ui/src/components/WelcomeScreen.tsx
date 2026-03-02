import React from 'react';
import { motion } from 'framer-motion';
import { FolderOpen, Keyboard, Sparkles, CheckCircle2, ArrowRight } from 'lucide-react';

interface WelcomeScreenProps {
    onNewPlan: () => void;
    onConnectProvider: () => void;
    onOpenRepo: () => void;
    onOpenCommandPalette: () => void;
    providerConnected?: boolean;
    providerName?: string;
    providerModel?: string;
}

/* ── Stepper step ── */
interface StepProps {
    number: number;
    title: string;
    description: string;
    done: boolean;
    active: boolean;
    action?: { label: string; onClick: () => void };
    delay: number;
}

const Step: React.FC<StepProps> = ({ number, title, description, done, active, action, delay }) => (
    <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 25, delay }}
        className={`flex items-start gap-4 p-4 rounded-xl border transition-all ${
            done
                ? 'border-emerald-500/20 bg-emerald-500/5'
                : active
                    ? 'border-accent-primary/30 bg-accent-primary/5 shadow-lg shadow-accent-primary/5'
                    : 'border-white/[0.04] bg-surface-2/30 opacity-50'
        }`}
    >
        <div
            className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm font-bold ${
                done
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : active
                        ? 'bg-accent-primary/20 text-accent-primary'
                        : 'bg-surface-3 text-text-tertiary'
            }`}
        >
            {done ? <CheckCircle2 size={16} /> : number}
        </div>
        <div className="flex-1 min-w-0">
            <div className={`text-sm font-semibold ${done ? 'text-emerald-400' : 'text-text-primary'}`}>
                {title}
            </div>
            <div className="text-[11px] text-text-secondary mt-0.5 leading-relaxed">
                {description}
            </div>
            {action && active && !done && (
                <button
                    onClick={action.onClick}
                    className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-primary text-white text-[11px] font-bold hover:bg-accent-primary/85 active:scale-[0.97] transition-all"
                >
                    {action.label}
                    <ArrowRight size={12} />
                </button>
            )}
        </div>
    </motion.div>
);

/* ── Quick action card ── */
const QuickAction = ({
    icon,
    title,
    description,
    onClick,
    delay,
}: {
    icon: React.ReactNode;
    title: string;
    description: string;
    onClick: () => void;
    delay: number;
}) => (
    <motion.button
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 25, delay }}
        onClick={onClick}
        className="group relative rounded-xl border border-white/[0.04] bg-surface-2/40 backdrop-blur-lg p-4 text-left transition-all hover:border-accent-primary/30 hover:bg-accent-primary/5 hover:shadow-lg hover:shadow-accent-primary/5 hover:-translate-y-0.5"
    >
        <div className="mb-2.5 transition-transform group-hover:scale-110">
            {icon}
        </div>
        <div className="text-[13px] font-semibold text-text-primary">{title}</div>
        <div className="mt-0.5 text-[10px] text-text-secondary leading-relaxed group-hover:text-text-primary/70 transition-colors">
            {description}
        </div>
    </motion.button>
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
        <section className="h-full w-full bg-surface-0 flex items-center justify-center p-6 relative overflow-hidden">
            {/* Background glow */}
            <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-accent-primary/8 blur-[120px] rounded-full pointer-events-none" />

            <div className="w-full max-w-2xl relative z-10">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                    className="text-center mb-10"
                >
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-white/[0.06] bg-surface-2/60 backdrop-blur text-accent-primary text-[10px] uppercase font-black tracking-widest mb-4">
                        <Sparkles size={11} className="animate-pulse" />
                        GIMO Orchestrator
                    </div>
                    <h1 className="text-3xl font-black text-text-primary tracking-tight">
                        Bienvenido
                    </h1>
                    <p className="text-sm text-text-secondary mt-2 max-w-md mx-auto">
                        {providerConnected
                            ? 'El sistema esta listo. Sigue los pasos para crear tu primer plan.'
                            : 'Configura un provider de IA para empezar a orquestar.'}
                    </p>
                </motion.div>

                {/* Stepper */}
                <div className="space-y-3 mb-10">
                    <Step
                        number={1}
                        title="Conectar Provider"
                        description={
                            providerConnected
                                ? `Conectado a ${providerName || 'Provider'}${providerModel ? ` / ${providerModel}` : ''}`
                                : 'Configura tu modelo LLM y clave de API para la inferencia.'
                        }
                        done={!!providerConnected}
                        active={!providerConnected}
                        action={{ label: 'Configurar', onClick: onConnectProvider }}
                        delay={0.1}
                    />
                    <Step
                        number={2}
                        title="Crear tu primer plan"
                        description="Describe un workflow en el chat o crea nodos manualmente en modo edicion."
                        done={false}
                        active={!!providerConnected}
                        action={{ label: 'Nuevo Plan', onClick: onNewPlan }}
                        delay={0.2}
                    />
                    <Step
                        number={3}
                        title="Explorar el sistema"
                        description="Usa Ctrl+K para acceso rapido, configura repositorios y revisa herramientas."
                        done={false}
                        active={!!providerConnected}
                        delay={0.3}
                    />
                </div>

                {/* Quick actions */}
                <div className="grid grid-cols-2 gap-3">
                    <QuickAction
                        icon={<FolderOpen size={18} className="text-accent-trust" />}
                        title="Repositorio"
                        description="Selecciona el directorio de trabajo."
                        onClick={onOpenRepo}
                        delay={0.35}
                    />
                    <QuickAction
                        icon={<Keyboard size={18} className="text-text-secondary" />}
                        title="Comandos"
                        description="Paleta de acceso rapido."
                        onClick={onOpenCommandPalette}
                        delay={0.4}
                    />
                </div>

                {/* Keyboard hint */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.5 }}
                    className="text-center mt-8"
                >
                    <span className="text-[10px] text-text-tertiary">
                        Presiona{' '}
                        <kbd className="bg-surface-3/60 px-1.5 py-0.5 rounded border border-white/[0.06] text-text-secondary mx-0.5 font-mono">
                            Ctrl+K
                        </kbd>{' '}
                        para buscar
                    </span>
                </motion.div>
            </div>
        </section>
    );
};
