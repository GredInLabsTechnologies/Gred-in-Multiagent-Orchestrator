import React from 'react';

export const AuthSuccessTransition: React.FC<{ visible: boolean }> = ({ visible }) => {
    if (!visible) return null;
    return (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-surface-0/70 animate-fade-in">
            <div className="rounded-xl border border-accent-trust/40 bg-surface-2 px-6 py-4 text-center animate-materialize shadow-[0_0_28px_var(--glow-trust)]">
                <div className="text-accent-trust text-sm font-semibold">Acceso concedido</div>
                <div className="text-xs text-text-secondary">Inicializando interfaz...</div>
                <div className="mt-3 h-1 w-36 mx-auto rounded-full bg-surface-3 overflow-hidden">
                    <div className="h-full w-1/3 bg-accent-trust animate-indeterminate" />
                </div>
            </div>
        </div>
    );
};
