import { useState, useCallback } from 'react';
import {
    API_BASE,
    ProviderInfo,
    ProviderRolesConfig,
    ProviderValidatePayload,
    ProviderValidateResult,
    SaveActiveProviderPayload,
} from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { useProviderAuth } from './useProviderAuth';
import { useProviderCatalog } from './useProviderCatalog';

export const useProviders = () => {
    const [providers, setProviders] = useState<ProviderInfo[]>([]);
    const [providerCapabilities, setProviderCapabilities] = useState<Record<string, any>>({});
    const [effectiveState, setEffectiveState] = useState<Record<string, any>>({});
    const [roles, setRoles] = useState<ProviderRolesConfig | null>(null);
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
            const res = await fetchWithRetry(`${API_BASE}/ops/provider`, getRequestInit());
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
                const capsRes = await fetchWithRetry(`${API_BASE}/ops/provider/capabilities`, getRequestInit());
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
                setEffectiveState({});
                setRoles(null);
            }
        } catch (error) {
            console.error("Failed to load providers", error);
        } finally {
            setLoading(false);
        }
    }, []);

    const {
        catalogs,
        catalogLoading,
        loadCatalog,
        installModel,
        getInstallJob,
        listCliDependencies,
        installCliDependency,
        getCliDependencyInstallJob,
    } = useProviderCatalog(loadProviders);

    const { startCodexDeviceLogin, startClaudeLogin, fetchCliAuthStatus, cliLogout } = useProviderAuth();

    const validateProvider = useCallback(async (providerType: string, payload: ProviderValidatePayload) => {
        const res = await fetchWithRetry(`${API_BASE}/ops/connectors/${encodeURIComponent(providerType)}/validate`, {
            method: 'POST',
            ...getRequestInit(true),
            body: JSON.stringify(payload || {}),
        });
        if (!res.ok) throw new Error('Failed to validate provider credentials');
        const data = await res.json() as ProviderValidateResult;
        await loadProviders();
        return data;
    }, [loadProviders]);

    const saveActiveProvider = useCallback(async (payload: SaveActiveProviderPayload) => {
        const currentRes = await fetchWithRetry(`${API_BASE}/ops/provider`, getRequestInit());
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

        const safeAccountRef = ((): string | undefined => {
            const raw = String(payload.account || '').trim();
            if (!raw) return undefined;
            if (raw.toLowerCase().startsWith('env:')) return raw;
            if (/^\$\{[A-Z0-9_]+\}$/.test(raw)) return raw;
            return undefined;
        })();

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
                    ...(safeAccountRef ? { auth_ref: safeAccountRef } : {}),
                },
            },
        };

        const res = await fetchWithRetry(`${API_BASE}/ops/provider`, {
            method: 'PUT',
            ...getRequestInit(true),
            body: JSON.stringify(next),
        });
        if (!res.ok) throw new Error('Failed to save active provider');
        await loadProviders();
        return await res.json();
    }, [loadProviders, providerCapabilities]);

    const addProvider = async (config: any) => {
        const currentRes = await fetchWithRetry(`${API_BASE}/ops/provider`, getRequestInit());
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

        const res = await fetchWithRetry(`${API_BASE}/ops/provider`, {
            method: "PUT",
            ...getRequestInit(true),
            body: JSON.stringify(next)
        });
        if (!res.ok) throw new Error("Failed to add provider");
        await loadProviders();
    };

    const removeProvider = async (id: string) => {
        const currentRes = await fetchWithRetry(`${API_BASE}/ops/provider`, getRequestInit());
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

        const res = await fetchWithRetry(`${API_BASE}/ops/provider`, {
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
            const res = await fetchWithRetry(`${API_BASE}/ops/connectors/${encodeURIComponent(provider.type)}/validate`, {
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
        fetchCliAuthStatus,
        cliLogout,
        listCliDependencies,
        installCliDependency,
        getCliDependencyInstallJob,
    };
};
