import React from 'react';

export const AuthLoadingOverlay: React.FC<{ visible: boolean; label?: string }> = ({ visible, label = 'Verificando credenciales...' }) => {
    if (!visible) return null;
    return (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-surface-0/70 backdrop-blur-sm animate-fade-in">
            <div className="relative w-80 rounded-xl border border-border-primary bg-surface-2 p-4 overflow-hidden animate-materialize">
                <div className="pointer-events-none absolute -top-10 -right-8 h-24 w-24 rounded-full border border-accent-primary/30 animate-orbit" />
                <div className="text-xs uppercase tracking-wider text-text-secondary mb-2">Autenticación</div>
                <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden mb-2">
                    <div className="h-full w-1/3 bg-accent-primary animate-indeterminate" />
                </div>
                <p className="text-sm text-text-primary">{label}</p>
            </div>
        </div>
    );
};
