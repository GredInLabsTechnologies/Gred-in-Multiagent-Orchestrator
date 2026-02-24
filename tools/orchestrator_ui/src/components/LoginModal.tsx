import { useState, type FormEvent } from 'react';
import { API_BASE } from '../types';

interface Props {
    onAuthenticated: () => void;
}

export function LoginModal({ onAuthenticated }: Props) {
    // El acceso requiere un token manual por seguridad.
    const [token, setToken] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ token: token.trim() }),
            });

            if (!res.ok) {
                const data = await res.json().catch(() => ({ detail: 'Error de conexion' }));
                setError(data.detail || `HTTP ${res.status}`);
                return;
            }

            onAuthenticated();
        } catch {
            setError('No se puede conectar al servidor');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#1c1c1e] flex items-center justify-center p-6">
            <form
                onSubmit={handleSubmit}
                className="w-full max-w-sm bg-[#2c2c2e] rounded-2xl border border-[#3a3a3c] p-8 space-y-6"
            >
                <div className="text-center space-y-1">
                    <h1 className="text-xl font-semibold text-white">GIMO</h1>
                    <p className="text-sm text-[#86868b]">Introduce tu token de acceso</p>
                </div>

                <div className="space-y-2">
                    <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        placeholder="Token"
                        autoFocus
                        className="w-full px-4 py-3 bg-[#1c1c1e] border border-[#3a3a3c] rounded-xl text-white text-sm
                                   placeholder-[#636366] focus:outline-none focus:border-[#0a84ff] transition-colors"
                    />
                    {error && (
                        <p className="text-xs text-[#ff3b30]">{error}</p>
                    )}
                </div>

                <button
                    type="submit"
                    disabled={loading || !token.trim()}
                    className="w-full py-3 bg-[#0a84ff] text-white text-sm font-medium rounded-xl
                               hover:bg-[#0a84ff]/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                    {loading ? 'Verificando...' : 'Entrar'}
                </button>

                <p className="text-[10px] text-[#48484a] text-center">
                    El token se encuentra en <code className="text-[#636366]">.orch_token</code>
                </p>
            </form>
        </div>
    );
}
