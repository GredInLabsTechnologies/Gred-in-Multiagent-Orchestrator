import { useState, useCallback } from 'react';
import {
    API_BASE,
    CliDependencyInstallResult,
    CliDependencyStatus,
    ProviderCatalogResponse,
    ProviderInfo,
    ProviderInstallResult,
    ProviderRolesConfig,
    ProviderValidatePayload,
    ProviderValidateResult,
    SaveActiveProviderPayload,
} from '../types';

export const useProviders = () => {
    const [providers, setProviders] = useState<ProviderInfo[]>([]);
    const [nodes, setNodes] = useState<any>({});
    const [providerCapabilities, setProviderCapabilities] = useState<Record<string, any>>({});
    const [effectiveState, setEffectiveState] = useState<Record<string, any>>({});
    const [roles, setRoles] = useState<ProviderRolesConfig | null>(null);
    const [catalogs, setCatalogs] = useState<Record<string, ProviderCatalogResponse>>({});
    const [catalogLoading, setCatalogLoading] = useState<Record<string, boolean>>({});
    const [loading, setLoading] = useState(false);

    const mapOpsConfigToProviders = (cfg: any): ProviderInfo[] => {
        const providers = cfg?.providers ?? {};
        return Object.entries(providers).map(([id, entry]: [string, any]) => {
            const capabilities = entry?.capabilities ?? {};
            const isLocal = !Boolean(capabilities?.requires_remote_api);
            return {
                id,
                type: entry?.provider_type || entry?.type || 'custom_openai_compatible',
                is_local: isLocal,
                capabilities,
                model: entry?.model_id || entry?.model,
                auth_mode: entry?.auth_mode ?? null,
                auth_ref: entry?.auth_ref ?? null,
                config: {
                    display_name: entry?.display_name,
                    base_url: entry?.base_url,
                    model: entry?.model,
                }
            };
        });
    };

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

    const loadProviders = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/ops/provider`, getRequestInit());
            if (res.ok) {
                const data = await res.json();
                setProviders(mapOpsConfigToProviders(data));
                setEffectiveState(data?.effective_state || {});
                const fallbackRoles = data?.orchestrator_provider
                    ? {
                        orchestrator: {
                            provider_id: data.orchestrator_provider,
                            model: data.orchestrator_model || data.model_id || '',
                        },
                        workers: data?.worker_provider
                            ? [{ provider_id: data.worker_provider, model: data.worker_model || '' }]
                            : [],
                    }
                    : null;
                setRoles(data?.roles || fallbackRoles);
                const capsRes = await fetch(`${API_BASE}/ops/provider/capabilities`, getRequestInit());
                if (capsRes.ok) {
                    const caps = await capsRes.json();
                    const normalizedCaps = Object.fromEntries(
                        Object.entries(caps.items || {}).map(([ptype, value]: [string, any]) => {
                            const authModes = Array.from(new Set(((value?.auth_modes_supported as string[] | undefined) || []).map(normalizeAuthMode)));
                            return [ptype, { ...value, auth_modes_supported: authModes }];
                        })
                    );
                    setProviderCapabilities(normalizedCaps);
                }
            } else {
                // legacy bridge fallback
                const legacyRes = await fetch(`${API_BASE}/ui/providers`, getRequestInit());
                if (legacyRes.ok) {
                    const legacyData = await legacyRes.json();
                    setProviders(Array.isArray(legacyData) ? legacyData : (legacyData.providers ?? []));
                }
                setEffectiveState({});
                setRoles(null);
            }

            const nodeRes = await fetch(`${API_BASE}/ui/nodes`, getRequestInit());
            if (nodeRes.ok) {
                const nodeData = await nodeRes.json();
                setNodes(nodeData);
            }
        } catch (error) {
            console.error("Failed to load providers", error);
        } finally {
            setLoading(false);
        }
    }, []);

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

    const validateProvider = useCallback(async (providerType: string, payload: ProviderValidatePayload) => {
        const res = await fetch(`${API_BASE}/ops/connectors/${encodeURIComponent(providerType)}/validate`, {
            method: 'POST',
            ...getRequestInit(true),
            body: JSON.stringify(payload || {}),
        });
        if (!res.ok) throw new Error('Failed to validate provider credentials');
        const data = await res.json() as ProviderValidateResult;
        await loadProviders();
        return data;
    }, [loadProviders]);

    const startCodexDeviceLogin = useCallback(async () => {
        const res = await fetch(`${API_BASE}/ops/connectors/codex/login`, {
            method: 'POST',
            ...getRequestInit(true),
        });
        const data = await res.json().catch(() => ({}));
        if (data?.status === 'error') {
            const err: any = new Error(data?.message || 'Codex login error');
            if (data?.action) err.action = data.action;
            throw err;
        }
        if (!res.ok) {
            const message = data?.message || data?.detail || 'Failed to start Codex device login flow';
            const err: any = new Error(message);
            if (data?.action) err.action = data.action;
            throw err;
        }
        return data;
    }, []);

    const startClaudeLogin = useCallback(async () => {
        const res = await fetch(`${API_BASE}/ops/connectors/claude/login`, {
            method: 'POST',
            ...getRequestInit(true),
        });
        if (!res.ok) throw new Error('Failed to start Claude login flow');
        return await res.json();
    }, []);

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

    const saveActiveProvider = useCallback(async (payload: SaveActiveProviderPayload) => {
        const currentRes = await fetch(`${API_BASE}/ops/provider`, getRequestInit());
        if (!currentRes.ok) throw new Error('Failed to read provider config');
        const current = await currentRes.json();

        const providerType = payload.providerType;
        const providerId = payload.providerId;
        const targetRole = payload.roleTarget || (providerId.startsWith('ollama-worker-') ? 'worker' : 'orchestrator');
        const existing = current?.providers?.[providerId] || {};
        const capabilities = providerCapabilities[providerType] || existing.capabilities || {};

        const currentRoles = current?.roles;
        const fallbackOrchestratorProvider = currentRoles?.orchestrator?.provider_id || current?.orchestrator_provider || current?.active || providerId;
        const fallbackOrchestratorModel = currentRoles?.orchestrator?.model || current?.orchestrator_model || current?.model_id || payload.modelId;
        const fallbackWorkers = Array.isArray(currentRoles?.workers)
            ? currentRoles.workers
            : (current?.worker_provider
                ? [{ provider_id: current.worker_provider, model: current?.worker_model || '' }]
                : []);

        const nextRoles = {
            orchestrator: {
                provider_id: fallbackOrchestratorProvider,
                model: fallbackOrchestratorModel,
            },
            workers: [...fallbackWorkers],
        };

        if (targetRole === 'worker') {
            const workerBinding = { provider_id: providerId, model: payload.modelId };
            const workerIdx = nextRoles.workers.findIndex((w: any) => w.provider_id === providerId);
            if (workerIdx >= 0) nextRoles.workers[workerIdx] = workerBinding;
            else nextRoles.workers.push(workerBinding);
        } else {
            nextRoles.orchestrator = { provider_id: providerId, model: payload.modelId };
        }

        const next = {
            ...current,
            active: nextRoles.orchestrator.provider_id,
            provider_type: providerType,
            model_id: nextRoles.orchestrator.model,
            auth_mode: payload.authMode,
            roles: nextRoles,
            orchestrator_provider: nextRoles.orchestrator.provider_id,
            orchestrator_model: nextRoles.orchestrator.model,
            worker_provider: nextRoles.workers[0]?.provider_id || null,
            worker_model: nextRoles.workers[0]?.model || null,
            providers: {
                ...(current.providers || {}),
                [providerId]: {
                    ...existing,
                    type: existing.type || providerType,
                    provider_type: providerType,
                    display_name: existing.display_name || providerId,
                    base_url: payload.baseUrl || existing.base_url || (!capabilities.requires_remote_api ? 'http://localhost:11434/v1' : undefined),
                    auth_mode: payload.authMode,
                    model: payload.modelId,
                    model_id: payload.modelId,
                    capabilities,
                    ...(payload.apiKey ? { api_key: payload.apiKey } : {}),
                    ...(payload.account ? { auth_ref: payload.account } : {}),
                },
            },
        };

        const res = await fetch(`${API_BASE}/ops/provider`, {
            method: 'PUT',
            ...getRequestInit(true),
            body: JSON.stringify(next),
        });
        if (!res.ok) throw new Error('Failed to save active provider');
        await loadProviders();
        return await res.json();
    }, [loadProviders, providerCapabilities]);

    const addProvider = async (config: any) => {
        const currentRes = await fetch(`${API_BASE}/ops/provider`, getRequestInit());
        if (!currentRes.ok) throw new Error("Failed to read provider config");
        const current = await currentRes.json();

        const providerId = config.id;
        const rawType = config.provider_type || config.type || 'custom_openai_compatible';
        const providerType = rawType;
        const next = {
            ...current,
            providers: {
                ...(current.providers || {}),
                [providerId]: {
                    ...(current.providers?.[providerId] || {}),
                    type: rawType,
                    provider_type: providerType,
                    display_name: config.display_name || providerId,
                    base_url: config.base_url,
                    api_key: config.api_key || null,
                    model: config.model || config.default_model || 'gpt-4o-mini',
                }
            },
            active: current.active || providerId,
        };

        const res = await fetch(`${API_BASE}/ops/provider`, {
            method: "PUT",
            ...getRequestInit(true),
            body: JSON.stringify(next)
        });
        if (!res.ok) throw new Error("Failed to add provider");
        await loadProviders();
    };

    const removeProvider = async (id: string) => {
        const currentRes = await fetch(`${API_BASE}/ops/provider`, getRequestInit());
        if (!currentRes.ok) throw new Error("Failed to read provider config");
        const current = await currentRes.json();
        const nextProviders = { ...(current.providers || {}) };
        delete nextProviders[id];
        const nextKeys = Object.keys(nextProviders);
        if (nextKeys.length === 0) throw new Error("Se requiere al menos un provider");

        const next = {
            ...current,
            providers: nextProviders,
            active: current.active === id ? nextKeys[0] : current.active,
        };

        const res = await fetch(`${API_BASE}/ops/provider`, {
            method: "PUT",
            ...getRequestInit(true),
            body: JSON.stringify(next),
        });
        if (!res.ok) throw new Error("Failed to remove provider");
        await loadProviders();
    };

    const testProvider = async (id: string): Promise<{ healthy: boolean; message: string }> => {
        const provider = providers.find((p) => p.id === id);
        if (!provider) {
            return { healthy: false, message: `Provider no encontrado: ${id}` };
        }

        const payload: ProviderValidatePayload = {
            base_url: provider.config?.base_url || undefined,
        };

        if (provider.auth_mode === 'account' && provider.auth_ref) {
            payload.account = provider.auth_ref;
        }

        try {
            const res = await fetch(`${API_BASE}/ops/connectors/${encodeURIComponent(provider.type)}/validate`, {
                method: 'POST',
                ...getRequestInit(true),
                body: JSON.stringify(payload),
            });

            const data = res.ok ? await res.json() : null;
            const healthy = Boolean(data?.valid);
            await loadProviders();
            return {
                healthy,
                message: healthy
                    ? `Provider ${id} accesible`
                    : (data?.error_actionable || 'Provider no accesible'),
            };
        } catch {
            return { healthy: false, message: 'Error de conexion al probar el provider' };
        }
    };

    return {
        providers,
        providerCapabilities,
        effectiveState,
        roles,
        catalogs,
        catalogLoading,
        nodes,
        loading,
        loadProviders,
        loadCatalog,
        installModel,
        getInstallJob,
        validateProvider,
        saveActiveProvider,
        addProvider,
        removeProvider,
        testProvider,
        startCodexDeviceLogin,
        startClaudeLogin,
        listCliDependencies,
        installCliDependency,
        getCliDependencyInstallJob,
    };
};
