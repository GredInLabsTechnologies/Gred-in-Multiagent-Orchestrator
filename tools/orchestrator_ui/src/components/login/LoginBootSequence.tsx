import React from 'react';

interface Props {
    done: boolean;
}

export const LoginBootSequence: React.FC<Props> = ({ done }) => {
    return (
        <div className={`absolute inset-0 z-20 flex items-center justify-center transition-opacity duration-300 ${done ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(59,130,246,0.12),transparent_45%),radial-gradient(circle_at_55%_62%,rgba(90,159,143,0.10),transparent_50%)]" />

            <div className={`relative w-[480px] max-w-[92vw] rounded-2xl border border-border-primary bg-surface-1/85 backdrop-blur-xl p-6 overflow-hidden ${done ? 'animate-zoom-fade-out' : 'animate-materialize'}`}>
                <div className="absolute -inset-16 opacity-60 pointer-events-none">
                    <div className="absolute left-1/2 top-1/2 h-56 w-56 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent-primary/25 animate-orbit" />
                </div>

                <div className="text-center mb-4 relative">
                    <h1 className="text-text-primary text-xl font-black tracking-[0.32em]">GIMO</h1>
                    <p className="text-[10px] uppercase tracking-[0.28em] text-text-tertiary mt-1">Fortress Runtime</p>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-surface-3/60 mb-3">
                    <div className="h-full w-1/3 bg-accent-primary animate-scan-line" />
                </div>
                <div className="font-mono text-[11px] text-text-secondary mb-4 overflow-hidden whitespace-nowrap border-r border-accent-primary/40 w-full animate-type-in">
                    Inicializando sistema y módulos de autenticación...
                </div>
                <div className="grid grid-cols-4 gap-2 text-[10px] font-bold uppercase tracking-wider">
                    <span className="rounded-md border border-border-primary bg-surface-2 px-2 py-1 text-accent-primary animate-slide-in-up [animation-delay:0ms]">Licencia</span>
                    <span className="rounded-md border border-border-primary bg-surface-2 px-2 py-1 text-text-secondary animate-slide-in-up [animation-delay:70ms]">Red</span>
                    <span className="rounded-md border border-border-primary bg-surface-2 px-2 py-1 text-accent-trust animate-slide-in-up [animation-delay:120ms]">Seguridad</span>
                    <span className="rounded-md border border-border-primary bg-surface-2 px-2 py-1 text-accent-approval animate-slide-in-up [animation-delay:170ms]">Motor</span>
                </div>
            </div>
        </div>
    );
};
