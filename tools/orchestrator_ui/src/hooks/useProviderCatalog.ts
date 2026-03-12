import { useState, useCallback } from 'react';
import {
    API_BASE,
    CliDependencyInstallResult,
    CliDependencyStatus,
    ProviderCatalogResponse,
    ProviderInstallResult,
} from '../types';

const getRequestInit = (includeJson: boolean = false): RequestInit => ({
    credentials: 'include',
    headers: {
        ...(includeJson ? { 'Content-Type': 'application/json' } : {}),
    },
});

const normalizeAuthMode = (mode: string): string => {
    if (mode === 'api_key_optional') return 'api_key';
    return mode;
};

export const useProviderCatalog = (loadProviders: () => Promise<void>) => {
    const [catalogs, setCatalogs] = useState<Record<string, ProviderCatalogResponse>>({});
    const [catalogLoading, setCatalogLoading] = useState<Record<string, boolean>>({});

    const loadCatalog = useCallback(async (providerType: string) => {
        if (!providerType) return null;
        setCatalogLoading(prev => ({ ...prev, [providerType]: true }));
        try {
            const res = await fetch(`${API_BASE}/ops/connectors/${encodeURIComponent(providerType)}/models`, getRequestInit());
            if (!res.ok) throw new Error('Failed to load provider catalog');
            const data: ProviderCatalogResponse = await res.json();
            const normalizedAuthModes = Array.from(new Set((data.auth_modes_supported || []).map(normalizeAuthMode)));
            const normalizedData: ProviderCatalogResponse = {
                ...data,
                auth_modes_supported: normalizedAuthModes,
            };
            setCatalogs(prev => ({ ...prev, [providerType]: normalizedData }));
            return normalizedData;
        } finally {
            setCatalogLoading(prev => ({ ...prev, [providerType]: false }));
        }
    }, []);

    const installModel = useCallback(async (providerType: string, modelId: string) => {
        const res = await fetch(`${API_BASE}/ops/connectors/${encodeURIComponent(providerType)}/models/install`, {
            method: 'POST',
            ...getRequestInit(true),
            body: JSON.stringify({ model_id: modelId }),
        });
        if (!res.ok) throw new Error('Failed to install model');
        const data = await res.json() as ProviderInstallResult;
        if (data.status === 'done' || data.status === 'error') {
            await loadCatalog(providerType);
        }
        return data;
    }, [loadCatalog]);

    const getInstallJob = useCallback(async (providerType: string, jobId: string) => {
        const res = await fetch(`${API_BASE}/ops/connectors/${encodeURIComponent(providerType)}/models/install/${encodeURIComponent(jobId)}`, getRequestInit());
        if (!res.ok) throw new Error('Failed to fetch install job status');
        const data = await res.json() as ProviderInstallResult;
        if (data.status === 'done' || data.status === 'error') {
            await loadCatalog(providerType);
            await loadProviders();
        }
        return data;
    }, [loadCatalog, loadProviders]);

    const listCliDependencies = useCallback(async () => {
        const res = await fetch(`${API_BASE}/ops/system/dependencies`, getRequestInit());
        if (!res.ok) throw new Error('Failed to list CLI dependencies');
        const data = await res.json() as { items: CliDependencyStatus[]; count: number };
        return data;
    }, []);

    const installCliDependency = useCallback(async (dependencyId: string) => {
        const res = await fetch(`${API_BASE}/ops/system/dependencies/install`, {
            method: 'POST',
            ...getRequestInit(true),
            body: JSON.stringify({ dependency_id: dependencyId }),
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body?.detail || 'Failed to install CLI dependency');
        }
        return await res.json() as CliDependencyInstallResult;
    }, []);

    const getCliDependencyInstallJob = useCallback(async (dependencyId: string, jobId: string) => {
        const res = await fetch(`${API_BASE}/ops/system/dependencies/install/${encodeURIComponent(dependencyId)}/${encodeURIComponent(jobId)}`, getRequestInit());
        if (!res.ok) throw new Error('Failed to fetch dependency install job');
        return await res.json() as CliDependencyInstallResult;
    }, []);

    return {
        catalogs,
        catalogLoading,
        loadCatalog,
        installModel,
        getInstallJob,
        listCliDependencies,
        installCliDependency,
        getCliDependencyInstallJob,
    };
};
