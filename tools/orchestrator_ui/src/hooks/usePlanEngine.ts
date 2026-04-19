import { useState, useCallback } from 'react';
import { Plan, PlanCreateRequest, API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { useSocketSubscription } from './useRealtimeChannel';

export function usePlanEngine() {
    const [currentPlan, setCurrentPlan] = useState<Plan | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Real-time updates
    useSocketSubscription('plan_update', (updatedPlan: Plan) => {
        if (currentPlan?.id === updatedPlan.id) {
            setCurrentPlan(updatedPlan);
        }
    }, [currentPlan]);

    const createPlan = useCallback(async (req: PlanCreateRequest) => {
        setLoading(true);
        setError(null);
        try {
            // Canonical surface: POST /ops/generate produces an OpsDraft via
            // the cognitive pipeline. Prompt travels as a query param.
            //
            // /ops/generate only accepts a single `prompt` field; the form
            // exposes `title` + `task_description`, so we fold the title
            // into the prompt (as a heading) to avoid silently dropping it.
            const description = (req as { task_description?: string; prompt?: string }).task_description
                || (req as { prompt?: string }).prompt
                || '';
            const title = (req as { title?: string }).title || '';
            const prompt = title && description
                ? `${title}\n\n${description}`
                : (title || description);
            const url = `${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`;
            const response = await fetchWithRetry(url, {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to create plan');
            const plan: Plan = await response.json();
            setCurrentPlan(plan);
            return plan;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchPlan = useCallback(async (planId: string) => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts/${planId}`, {
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to fetch plan');
            const plan: Plan = await response.json();
            setCurrentPlan(plan);
            return plan;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    const approvePlan = useCallback(async (planId: string) => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts/${planId}/approve`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Failed to approve plan');
            // Optimistic update not needed as socket will trigger
            return true;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return false;
        } finally {
            setLoading(false);
        }
    }, []);

    const updatePlan = useCallback(async (planId: string, updates: Partial<Plan>) => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts/${planId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify(updates),
            });
            if (!response.ok) throw new Error('Failed to update plan');
            const plan: Plan = await response.json();
            setCurrentPlan(plan);
            return plan;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    return {
        currentPlan,
        loading,
        error,
        createPlan,
        fetchPlan,
        approvePlan,
        updatePlan,
        setCurrentPlan,
    };
}
