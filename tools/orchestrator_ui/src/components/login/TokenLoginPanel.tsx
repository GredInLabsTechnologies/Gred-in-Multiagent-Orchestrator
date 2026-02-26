import React, { type FormEvent } from 'react';

interface Props {
    token: string;
    loading: boolean;
    onTokenChange: (value: string) => void;
    onSubmit: (e: FormEvent) => void;
}

export const TokenLoginPanel: React.FC<Props> = ({ token, loading, onTokenChange, onSubmit }) => {
    return (
        <form onSubmit={onSubmit} className="space-y-3 animate-slide-in-up">
            <input
                type="password"
                value={token}
                onChange={(e) => onTokenChange(e.target.value)}
                placeholder="Token local"
                className="w-full px-4 py-3 rounded-xl bg-surface-2 border border-border-primary text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-border-focus"
            />
            <button
                type="submit"
                disabled={loading || !token.trim()}
                className="w-full py-3 rounded-xl bg-surface-3 hover:bg-surface-3/80 disabled:opacity-50 text-text-primary text-sm font-semibold"
            >
                {loading ? 'Verificando...' : 'Entrar con token'}
            </button>
        </form>
    );
};
