import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { FolderOpen, Keyboard, Sparkles, CheckCircle2, ArrowRight, X } from 'lucide-react';

interface WelcomeScreenProps {
    onNewPlan: () => void;
    onConnectProvider: () => void;
    onOpenRepo: () => void;
    onOpenCommandPalette: () => void;
    onDismiss: (neverShowAgain: boolean) => void;
    providerConnected?: boolean;
    providerName?: string;
    providerModel?: string;
    repoConnected?: boolean;
    repoPath?: string;
    hasActivity?: boolean;
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
        className={`flex items-start gap-4 p-4 rounded-xl border transition-all ${done
                ? 'border-emerald-500/20 bg-emerald-500/5'
                : active
                    ? 'border-accent-primary/30 bg-accent-primary/5 shadow-lg shadow-accent-primary/5'
                    : 'border-white/[0.04] bg-surface-2/30 opacity-50'
            }`}
    >
        <div
            className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm font-bold ${done
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
    onDismiss,
    providerConnected,
    providerName,
    providerModel,
    repoConnected,
    repoPath,
    hasActivity,
}) => {
    const [neverShowAgain, setNeverShowAgain] = useState(false);

    const stepProviderDone = !!providerConnected;
    const stepRepoDone = !!repoConnected;
    const stepActivityDone = !!hasActivity;

    return (
        <section className="w-full rounded-2xl border border-white/[0.08] bg-surface-1/95 backdrop-blur-xl p-5 md:p-6 relative overflow-hidden shadow-2xl">
            {/* Background glow */}
            <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-accent-primary/8 blur-[120px] rounded-full pointer-events-none" />

            <div className="w-full relative z-10">
                <div className="flex justify-end mb-2">
                    <button
                        onClick={() => onDismiss(neverShowAgain)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-white/[0.08] bg-surface-2/70 text-text-secondary hover:text-text-primary transition-colors text-[11px]"
                        title="Cerrar onboarding"
                    >
                        <X size={12} />
                        Cerrar
                    </button>
                </div>

                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                    className="text-center mb-6"
                >
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-white/[0.06] bg-surface-2/60 backdrop-blur text-accent-primary text-[10px] uppercase font-black tracking-widest mb-4">
                        <Sparkles size={11} className="animate-pulse" />
                        GIMO Orchestrator
                    </div>
                    <h1 className="text-3xl font-black text-text-primary tracking-tight">
                        Bienvenido
                    </h1>
                    <p className="text-sm text-text-secondary mt-2 max-w-md mx-auto">
                        Guía rápida no bloqueante. Puedes seguir trabajando en el grafo aunque no completes todo ahora.
                    </p>
                </motion.div>

                {/* Stepper */}
                <div className="space-y-3 mb-6">
                    <Step
                        number={1}
                        title="Conectar Provider"
                        description={
                            stepProviderDone
                                ? `Conectado a ${providerName || 'Provider'}${providerModel ? ` / ${providerModel}` : ''}`
                                : 'Configura tu modelo LLM y clave de API para la inferencia.'
                        }
                        done={stepProviderDone}
                        active={!stepProviderDone}
                        action={{ label: 'Configurar', onClick: onConnectProvider }}
                        delay={0.1}
                    />
                    <Step
                        number={2}
                        title="Seleccionar repositorio"
                        description={
                            stepRepoDone
                                ? `Repositorio activo: ${repoPath || 'configurado'}`
                                : 'Selecciona repo de trabajo en Operaciones.'
                        }
                        done={stepRepoDone}
                        active={stepProviderDone && !stepRepoDone}
                        action={{ label: 'Abrir Operaciones', onClick: onOpenRepo }}
                        delay={0.2}
                    />
                    <Step
                        number={3}
                        title="Actividad inicial"
                        description="Crea o ejecuta al menos un draft/run para completar el onboarding funcional."
                        done={stepActivityDone}
                        active={stepProviderDone && stepRepoDone && !stepActivityDone}
                        action={{ label: 'Nuevo Plan', onClick: onNewPlan }}
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

                <div className="mt-5 flex items-center justify-between gap-3 flex-wrap">
                    <label className="inline-flex items-center gap-2 text-[11px] text-text-secondary">
                        <input
                            type="checkbox"
                            checked={neverShowAgain}
                            onChange={(e) => setNeverShowAgain(e.target.checked)}
                            className="rounded border border-white/20 bg-surface-2"
                        />
                        No mostrar más este onboarding
                    </label>

                    <button
                        onClick={() => onDismiss(neverShowAgain)}
                        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent-primary text-white text-[11px] font-bold hover:bg-accent-primary/85"
                    >
                        Continuar al grafo
                        <ArrowRight size={12} />
                    </button>
                </div>

                {/* Keyboard hint */}
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.5 }}
                    className="text-center mt-6"
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
