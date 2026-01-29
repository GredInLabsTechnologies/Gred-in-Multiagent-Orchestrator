import { useState, useCallback, useEffect } from 'react';
import { API_BASE } from '../types';

export interface SecurityEvent {
    timestamp: string;
    type: string;
    reason: string;
    actor: string;
    resolved: boolean;
}

export const useSecurityService = (token?: string) => {
    const [panicMode, setPanicMode] = useState(false);
    const [events, setEvents] = useState<SecurityEvent[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchSecurity = useCallback(async () => {
        try {
            const headers: HeadersInit = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/security/events`, { headers });
            if (!res.ok) {
                if (res.status === 503) {
                    setPanicMode(true);
                    return;
                }
                throw new Error('Failed to fetch security status');
            }
            const data = await res.json();
            setPanicMode(data.panic_mode);
            setEvents(data.events || []);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        }
    }, [token]);

    const clearPanic = useCallback(async () => {
        setIsLoading(true);
        try {
            const headers: HeadersInit = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/security/resolve?action=clear_panic`, {
                method: 'POST',
                headers
            });
            if (!res.ok) throw new Error('Failed to clear panic mode');

            await fetchSecurity();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
            setIsLoading(false);
        }
    }, [token, fetchSecurity]);

    useEffect(() => {
        fetchSecurity();
        const interval = setInterval(fetchSecurity, 10000);
        return () => clearInterval(interval);
    }, [fetchSecurity]);

    return {
        panicMode,
        events,
        isLoading,
        error,
        clearPanic,
        refresh: fetchSecurity
    };
};
