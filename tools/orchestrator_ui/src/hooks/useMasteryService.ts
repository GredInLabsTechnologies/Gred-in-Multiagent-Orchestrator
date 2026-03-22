import { useState, useCallback } from 'react';
import {
    API_BASE,
    UserEconomyConfig,
    MasteryStatus,
    CostAnalytics,
    BudgetForecast,
    MasteryRecommendation,
    PlanEconomySnapshot,
} from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { useToast } from '../components/Toast';

export function useMasteryService() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const { addToast } = useToast();

    const fetchOpts: RequestInit = { credentials: 'include' };

    const apiCall = useCallback(async <T>(fn: () => Promise<T>, label: string): Promise<T> => {
        setLoading(true);
        setError(null);
        try {
            return await fn();
        } catch (err: any) {
            const msg = err.message || 'An unexpected error occurred';
            setError(msg);
            addToast(`${label}: ${msg}`, 'error');
            throw err;
        } finally {
            setLoading(false);
        }
    }, [addToast]);

    const fetchConfig = useCallback(async (): Promise<UserEconomyConfig> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/config/economy`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Economy Config');
    }, [apiCall]);

    const saveConfig = useCallback(async (config: UserEconomyConfig): Promise<UserEconomyConfig> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/config/economy`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(config)
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Save Config');
    }, [apiCall]);

    const fetchStatus = useCallback(async (): Promise<MasteryStatus> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/status`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Mastery Status');
    }, [apiCall]);

    const fetchAnalytics = useCallback(async (days = 30): Promise<CostAnalytics> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/analytics?days=${days}`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Analytics');
    }, [apiCall]);

    const fetchForecast = useCallback(async (): Promise<BudgetForecast[]> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/forecast`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Budget Forecast');
    }, [apiCall]);

    const fetchRecommendations = useCallback(async (): Promise<MasteryRecommendation[]> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/recommendations`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            return data.recommendations || [];
        }, 'Recommendations');
    }, [apiCall]);

    const fetchPlanEconomy = useCallback(async (planId: string, days = 30): Promise<PlanEconomySnapshot> => {
        return apiCall(async () => {
            const res = await fetchWithRetry(`${API_BASE}/ops/mastery/plans/${planId}/economy?days=${days}`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }, 'Plan Economy');
    }, [apiCall]);

    const updatePlanAutonomy = useCallback(
        async (
            planId: string,
            level: 'manual' | 'advisory' | 'guided' | 'autonomous',
            nodeIds: string[] = [],
        ): Promise<PlanEconomySnapshot> => {
            return apiCall(async () => {
                const res = await fetchWithRetry(`${API_BASE}/ops/mastery/plans/${planId}/autonomy`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ level, node_ids: nodeIds }),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            }, 'Update Plan Autonomy');
        },
        [apiCall],
    );

    return {
        loading,
        error,
        fetchConfig,
        saveConfig,
        fetchStatus,
        fetchAnalytics,
        fetchForecast,
        fetchRecommendations,
        fetchPlanEconomy,
        updatePlanAutonomy,
    };
}
