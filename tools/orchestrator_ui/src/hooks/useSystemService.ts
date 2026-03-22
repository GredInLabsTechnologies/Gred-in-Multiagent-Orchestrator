import { useState, useCallback, useEffect } from 'react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

export type ServiceStatus = 'RUNNING' | 'STOPPED' | 'STARTING' | 'STOPPING' | 'UNKNOWN';

export const useSystemService = (_token?: string) => {
    const [status, setStatus] = useState<ServiceStatus>('UNKNOWN');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchStatus = useCallback(async () => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/service/status`, { credentials: 'include' });
            if (!res.ok) throw new Error('Failed to fetch service status');
            const data = await res.json();
            setStatus(data.status);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        }
    }, []);

    const controlService = useCallback(async (action: 'restart' | 'stop') => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/service/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });
            if (!res.ok) throw new Error(`Failed to ${action} service`);

            // Poll for status update after a short delay
            setTimeout(fetchStatus, 2000);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        } finally {
            setIsLoading(false);
        }
    }, [fetchStatus]);

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
