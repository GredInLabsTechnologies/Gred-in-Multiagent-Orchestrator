import { useState, useCallback } from 'react';
import { API_BASE, Trace, ObservabilityMetrics } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

interface UseObservabilityService {
    loading: boolean;
    error: string | null;
    getMetrics: () => Promise<ObservabilityMetrics | null>;
    getTraces: (limit?: number, offset?: number) => Promise<Trace[]>;
    getTraceDetail: (traceId: string) => Promise<Trace | null>;
}

export const useObservabilityService = (): UseObservabilityService => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const getMetrics = useCallback(async (): Promise<ObservabilityMetrics | null> => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/observability/metrics`, {
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to fetch metrics');
            return await response.json();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    const getTraces = useCallback(async (limit = 20, offset = 0): Promise<Trace[]> => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/observability/traces?limit=${limit}&offset=${offset}`, {
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to fetch traces');
            const payload = await response.json();
            if (Array.isArray(payload)) {
                return payload as Trace[];
            }
            if (payload && Array.isArray(payload.items)) {
                return payload.items as Trace[];
            }
            return [];
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return [];
        } finally {
            setLoading(false);
        }
    }, []);

    const getTraceDetail = useCallback(async (traceId: string): Promise<Trace | null> => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/observability/traces/${traceId}`, {
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to fetch trace details');
            return await response.json();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    return {
        loading,
        error,
        getMetrics,
        getTraces,
        getTraceDetail
    };
};
