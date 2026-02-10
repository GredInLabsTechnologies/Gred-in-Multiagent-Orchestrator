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
    // Server schema still uses `panic_mode`, but the UI/UX terminology is "LOCKDOWN".
    // Use "lockdown" internally, but expose compatibility aliases for backward compatibility.
    const [lockdown, setLockdown] = useState(false);
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
                    setLockdown(true);
                    return;
                }
                throw new Error('Failed to fetch security status');
            }
            const data = await res.json();
            setLockdown(Boolean(data.panic_mode));
            setEvents(data.events || []);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        }
    }, [token]);

    const clearLockdown = useCallback(async () => {
        setIsLoading(true);
        try {
            const headers: HeadersInit = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/security/resolve?action=clear_panic`, {
                method: 'POST',
                headers
            });
            if (!res.ok) throw new Error('Failed to clear lockdown');

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
        // Preferred terminology
        lockdown,
        clearLockdown,

        // Backward compatible terminology
        panicMode: lockdown,
        events,
        isLoading,
        error,
        clearPanic: clearLockdown,
        refresh: fetchSecurity
    };
};
