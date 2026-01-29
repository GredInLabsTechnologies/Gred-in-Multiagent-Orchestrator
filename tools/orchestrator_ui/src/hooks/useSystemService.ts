import { useState, useCallback, useEffect } from 'react';
import { API_BASE } from '../types';

export type ServiceStatus = 'RUNNING' | 'STOPPED' | 'STARTING' | 'STOPPING' | 'UNKNOWN';

export const useSystemService = (token?: string) => {
    const [status, setStatus] = useState<ServiceStatus>('UNKNOWN');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchStatus = useCallback(async () => {
        try {
            const headers: HeadersInit = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/service/status`, { headers });
            if (!res.ok) throw new Error('Failed to fetch service status');
            const data = await res.json();
            setStatus(data.status);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        }
    }, [token]);

    const controlService = useCallback(async (action: 'restart' | 'stop') => {
        setIsLoading(true);
        setError(null);
        try {
            const headers: HeadersInit = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/service/${action}`, {
                method: 'POST',
                headers
            });
            if (!res.ok) throw new Error(`Failed to ${action} service`);

            // Poll for status update after a short delay
            setTimeout(fetchStatus, 2000);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
            setIsLoading(false);
        }
    }, [token, fetchStatus]);

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, [fetchStatus]);

    return {
        status,
        isLoading,
        error,
        restart: () => controlService('restart'),
        stop: () => controlService('stop'),
        refresh: fetchStatus
    };
};
