import { useState, useCallback, useEffect, useRef } from 'react';
import {
    API_BASE,
    OpsPlan, OpsDraft, OpsApproved, OpsRun, OpsConfig,
    OpsApproveResponse, ProviderConfig
} from '../types';

const POLL_INTERVAL_MS = 3000;

export const useOpsService = (token?: string) => {
    const [plan, setPlan] = useState<OpsPlan | null>(null);
    const [drafts, setDrafts] = useState<OpsDraft[]>([]);
    const [approved, setApproved] = useState<OpsApproved[]>([]);
    const [runs, setRuns] = useState<OpsRun[]>([]);
    const [config, setConfigState] = useState<OpsConfig | null>(null);
    const [provider] = useState<ProviderConfig | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const getHeaders = useCallback(() => {
        const headers: HeadersInit = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    }, [token]);

    const fetchAll = useCallback(async () => {
        setIsLoading(true);
        try {
            const h = getHeaders();
            const [pRes, dRes, aRes, rRes, cRes] = await Promise.all([
                fetch(`${API_BASE}/ops/plan`, { headers: h }),
                fetch(`${API_BASE}/ops/drafts`, { headers: h }),
                fetch(`${API_BASE}/ops/approved`, { headers: h }),
                fetch(`${API_BASE}/ops/runs`, { headers: h }),
                fetch(`${API_BASE}/ops/config`, { headers: h }),
            ]);

            if (pRes.ok) setPlan(await pRes.json());
            if (dRes.ok) setDrafts(await dRes.json());
            if (aRes.ok) setApproved(await aRes.json());
            if (rRes.ok) setRuns(await rRes.json());
            if (cRes.ok) setConfigState(await cRes.json());

            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch OPS data');
        } finally {
            setIsLoading(false);
        }
    }, [getHeaders]);

    // Poll runs when there are active (pending/running) runs
    const refreshRuns = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/ops/runs`, { headers: getHeaders() });
            if (res.ok) setRuns(await res.json());
        } catch { /* silent */ }
    }, [getHeaders]);

    useEffect(() => {
        const hasActive = runs.some(r => r.status === 'pending' || r.status === 'running');
        if (hasActive && !pollRef.current) {
            pollRef.current = setInterval(refreshRuns, POLL_INTERVAL_MS);
        } else if (!hasActive && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [runs, refreshRuns]);

    const updatePlan = async (newPlan: OpsPlan) => {
        try {
            const res = await fetch(`${API_BASE}/ops/plan`, {
                method: 'PUT', headers: getHeaders(), body: JSON.stringify(newPlan)
            });
            if (!res.ok) throw new Error('Failed to update plan');
            setPlan(newPlan);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Update failed');
        }
    };

    const generateDraft = async (prompt: string) => {
        setIsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`, {
                method: 'POST', headers: getHeaders()
            });
            if (!res.ok) throw new Error('Generation failed');
            const newDraft = await res.json();
            setDrafts(prev => [newDraft, ...prev]);
            return newDraft;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Generation failed');
        } finally {
            setIsLoading(false);
        }
    };

    const approveDraft = async (id: string, autoRun?: boolean) => {
        try {
            const params = autoRun !== undefined ? `?auto_run=${autoRun}` : '';
            const res = await fetch(`${API_BASE}/ops/drafts/${id}/approve${params}`, {
                method: 'POST', headers: getHeaders()
            });
            if (!res.ok) throw new Error('Approval failed');
            const data: OpsApproveResponse = await res.json();
            setApproved(prev => [data.approved, ...prev]);
            setDrafts(prev => prev.map(d => d.id === id ? { ...d, status: 'approved' as const } : d));
            if (data.run) setRuns(prev => [data.run!, ...prev]);
            return data;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Approval failed');
        }
    };

    const rejectDraft = async (id: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${id}/reject`, {
                method: 'POST', headers: getHeaders()
            });
            if (!res.ok) throw new Error('Rejection failed');
            setDrafts(prev => prev.map(d => d.id === id ? { ...d, status: 'rejected' as const } : d));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Rejection failed');
        }
    };

    const startRun = async (approvedId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/runs`, {
                method: 'POST', headers: getHeaders(),
                body: JSON.stringify({ approved_id: approvedId })
            });
            if (!res.ok) throw new Error('Failed to start run');
            const newRun = await res.json();
            setRuns(prev => [newRun, ...prev]);
            return newRun;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Run failed');
        }
    };

    const cancelRun = async (runId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/runs/${runId}/cancel`, {
                method: 'POST', headers: getHeaders()
            });
            if (!res.ok) throw new Error('Cancel failed');
            const updated = await res.json();
            setRuns(prev => prev.map(r => r.id === runId ? updated : r));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Cancel failed');
        }
    };

    const updateConfig = async (newConfig: OpsConfig) => {
        try {
            const res = await fetch(`${API_BASE}/ops/config`, {
                method: 'PUT', headers: getHeaders(),
                body: JSON.stringify(newConfig)
            });
            if (!res.ok) throw new Error('Config update failed');
            setConfigState(await res.json());
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Config update failed');
        }
    };

    useEffect(() => { fetchAll(); }, [fetchAll]);

    return {
        plan, drafts, approved, runs, config, provider,
        isLoading, error,
        updatePlan, generateDraft, approveDraft, rejectDraft,
        startRun, cancelRun, updateConfig,
        refresh: fetchAll
    };
};
