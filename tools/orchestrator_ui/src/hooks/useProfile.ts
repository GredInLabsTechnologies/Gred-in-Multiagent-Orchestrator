import { useCallback, useEffect, useState } from 'react';
import { API_BASE, UserProfile } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

interface UseProfileState {
    profile: UserProfile | null;
    loading: boolean;
    error: string | null;
    unauthorized: boolean;
    refetch: () => Promise<void>;
}

export function useProfile(enabled = true): UseProfileState {
    const [profile, setProfile] = useState<UserProfile | null>(null);
    const [loading, setLoading] = useState<boolean>(enabled);
    const [error, setError] = useState<string | null>(null);
    const [unauthorized, setUnauthorized] = useState(false);

    const fetchProfile = useCallback(async () => {
        if (!enabled) {
            setLoading(false);
            setUnauthorized(false);
            setError(null);
            setProfile(null);
            return;
        }

        setLoading(true);
        setError(null);

        try {
            const res = await fetchWithRetry(`${API_BASE}/auth/profile`, {
                credentials: 'include',
            });

            if (res.status === 401) {
                setUnauthorized(true);
                setProfile(null);
                setError('Sesión expirada. Vuelve a iniciar sesión.');
                return;
            }

            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }

            const payload = await res.json() as UserProfile;
            setProfile(payload);
            setUnauthorized(false);
        } catch {
            setUnauthorized(false);
            setError('No se pudo cargar el perfil.');
        } finally {
            setLoading(false);
        }
    }, [enabled]);

    useEffect(() => {
        void fetchProfile();
    }, [fetchProfile]);

    useEffect(() => {
        if (!enabled) return;
        const timer = globalThis.setInterval(() => {
            void fetchProfile();
        }, 5 * 60 * 1000);
        return () => globalThis.clearInterval(timer);
    }, [enabled, fetchProfile]);

    return {
        profile,
        loading,
        error,
        unauthorized,
        refetch: fetchProfile,
    };
}
