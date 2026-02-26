import React from 'react';

interface Props {
    error: string;
    onRetry: () => void;
}

export const AuthErrorPanel: React.FC<Props> = ({ error, onRetry }) => {
    return (
        <div className="rounded-xl border border-accent-alert/40 bg-accent-alert/10 p-3 animate-shake">
            <div className="text-[10px] uppercase tracking-wider text-accent-alert/90 mb-1">Error de autenticación</div>
            <p className="text-xs text-accent-alert mb-2">{error}</p>
            <button onClick={onRetry} className="text-xs px-3 py-1.5 rounded-lg border border-accent-alert/40 text-accent-alert hover:bg-accent-alert/10 transition-colors duration-150">
                Reintentar
            </button>
        </div>
    );
};
