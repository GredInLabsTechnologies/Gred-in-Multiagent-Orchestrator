import React from 'react';

interface Props {
    loading: boolean;
    onLogin: () => void;
}

export const GoogleSSOPanel: React.FC<Props> = ({ loading, onLogin }) => {
    return (
        <div className="space-y-3 animate-slide-in-up">
            <p className="text-sm text-text-secondary">Inicia sesión con tu cuenta Google para sincronizar perfil y licencias.</p>
            <button
                type="button"
                onClick={onLogin}
                disabled={loading}
                className="w-full py-3 rounded-xl bg-accent-primary hover:bg-accent-primary/85 disabled:opacity-50 text-white text-sm font-semibold"
            >
                {loading ? 'Conectando con Google...' : 'Iniciar sesión con Google'}
            </button>
        </div>
    );
};
