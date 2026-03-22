import { useState, useCallback } from 'react';
import useSWR from 'swr';
import { API_BASE, EvalDataset, EvalRunRequest, EvalRunReport, EvalRunSummary, EvalRunDetail } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

const fetcher = (url: string) => {
    return fetchWithRetry(url, {
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
    }).then(async (res) => {
        const payload = await res.json().catch(() => null);
        if (!res.ok) {
            throw new Error((payload && payload.detail) || `HTTP ${res.status}`);
        }
        return payload;
    });
};

export const useEvalsService = (_token?: string) => {
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const getHeaders = useCallback(() => {
        return { 'Content-Type': 'application/json' } as HeadersInit;
    }, []);

    // SWR hooks for data fetching
    const { data: datasets, error: datasetsError, mutate: mutateDatasets } = useSWR<{ items: EvalDataset[], count: number }>(
        `${API_BASE}/ops/evals/datasets`,
        fetcher
    );

    const { data: runs, error: runsError, mutate: mutateRuns } = useSWR<EvalRunSummary[] | { items: EvalRunSummary[]; count: number }>(
        `${API_BASE}/ops/evals/runs`,
        fetcher
    );

    const createDataset = async (dataset: EvalDataset, versionTag?: string) => {
        setIsLoading(true);
        try {
            const params = versionTag ? `?version_tag=${encodeURIComponent(versionTag)}` : '';
            const res = await fetchWithRetry(`${API_BASE}/ops/evals/datasets${params}`, {
                method: 'POST',
                headers: getHeaders(),
                credentials: 'include',
                body: JSON.stringify(dataset)
            });
            if (!res.ok) throw new Error('Failed to create dataset');
            const data = await res.json();
            mutateDatasets();
            return data;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Create dataset failed');
            throw err;
        } finally {
            setIsLoading(false);
        }
    };

    const runEval = async (request: EvalRunRequest, failOnGate: boolean = false) => {
        setIsLoading(true);
        try {
            const params = `?fail_on_gate=${failOnGate}`;
            const res = await fetchWithRetry(`${API_BASE}/ops/evals/run${params}`, {
                method: 'POST',
                headers: getHeaders(),
                credentials: 'include',
                body: JSON.stringify(request)
            });
            if (!res.ok && res.status !== 412) throw new Error('Eval run failed');

            // 412 Precondition Failed is returned when gate fails but fail_on_gate is true
            // In this case, we still get the report in the body
            const report: EvalRunReport = await res.json();

            mutateRuns();
            return report;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Eval run failed');
            throw err;
        } finally {
            setIsLoading(false);
        }
    };

    const getRunDetail = async (runId: number) => {
        setIsLoading(true);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/evals/runs/${runId}`, {
                headers: getHeaders(),
                credentials: 'include',
            });
            if (!res.ok) throw new Error('Failed to fetch run detail');
            const detail: EvalRunDetail = await res.json();
            return detail;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Fetch run detail failed');
            throw err;
        } finally {
            setIsLoading(false);
        }
    };

    const datasetsList = Array.isArray(datasets?.items)
        ? datasets.items
        : [];

    const runsList = Array.isArray(runs)
        ? runs
        : (runs && Array.isArray(runs.items) ? runs.items : []);

    return {
        datasets: datasetsList,
        runs: runsList,
        isLoading: isLoading || ((!datasets && !datasetsError) || (!runs && !runsError)),
        error: error || (datasetsError ? 'Failed to load datasets' : null) || (runsError ? 'Failed to load runs' : null),
        createDataset,
        runEval,
        getRunDetail,
        mutateDatasets,
        mutateRuns
    };
};
