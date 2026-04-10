import React, { useMemo, useEffect, useCallback, useState } from 'react';
import { Card } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { useProviders } from '../hooks/useProviders';
import { useProviderSettingsState } from '../hooks/useProviderSettingsState';
import { useToast } from './Toast';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { Server, Cpu, CheckCircle2, AlertTriangle } from 'lucide-react';
import { CodexAuthSection } from './provider/CodexAuthSection';
import { ClaudeAuthSection } from './provider/ClaudeAuthSection';
import { OllamaLocalSection } from './provider/OllamaLocalSection';
import { ModelSelector } from './provider/ModelSelector';
import { ProviderList } from './provider/ProviderList';

/* ── Friendly provider type labels ── */
const PROVIDER_LABELS: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    google: 'Google',
    mistral: 'Mistral',
    cohere: 'Cohere',
    deepseek: 'DeepSeek',
    qwen: 'Qwen',
    moonshot: 'Moonshot',
    zai: 'Z.ai',
    minimax: 'MiniMax',
    baidu: 'Baidu',
    tencent: 'Tencent',
    bytedance: 'ByteDance',
    iflytek: 'iFlyTek',
    '01-ai': '01.AI',
    codex: 'Codex CLI',
    claude: 'Anthropic (Claude CLI)',
    together: 'Together',
    fireworks: 'Fireworks',
    replicate: 'Replicate',
    huggingface: 'HuggingFace',
    'azure-openai': 'Azure OpenAI',
    'aws-bedrock': 'AWS Bedrock',
    'vertex-ai': 'Vertex AI',
    ollama: 'Ollama',
    vllm: 'vLLM',
    'llama-cpp': 'llama.cpp',
    tgi: 'Text Generation Inference (TGI)',
    ollama_local: 'Ollama (Local)',
    groq: 'Groq',
    'cloudflare-workers-ai': 'Cloudflare Workers AI',
    openrouter: 'OpenRouter',
    custom_openai_compatible: 'OpenAI Compatible',
};

const KNOWN_PROVIDER_TYPES = [
    'openai', 'anthropic', 'google', 'mistral', 'cohere', 'deepseek', 'qwen', 'moonshot',
    'zai', 'minimax', 'baidu', 'tencent', 'bytedance', 'iflytek', '01-ai', 'codex', 'claude',
    'together', 'fireworks', 'replicate', 'huggingface', 'azure-openai', 'aws-bedrock',
    'vertex-ai', 'ollama', 'vllm', 'llama-cpp', 'tgi', 'ollama_local', 'groq', 'cloudflare-workers-ai', 'openrouter',
    'custom_openai_compatible',
];

export const ProviderSettings: React.FC = () => {
    const {
        providers,
        providerCapabilities,
        effectiveState,
        roles,
        catalogs,
        catalogLoading,
        nodes,
        loadProviders,
        loadCatalog,
        installModel,
        getInstallJob,
        validateProvider,
        saveActiveProvider,
        removeProvider,
        testProvider,
        startCodexDeviceLogin,
        startClaudeLogin,
        fetchCliAuthStatus,
        cliLogout,
        installCliDependency,
        getCliDependencyInstallJob,
    } = useProviders();
    const {
        providerType, setProviderType,
        providerId, setProviderId,
        modelId, setModelId,
        providerSearch, setProviderSearch,
        modelSearch, setModelSearch,
        providerDropdownOpen, setProviderDropdownOpen,
        modelDropdownOpen, setModelDropdownOpen,
        authMode, setAuthMode,
        apiKey, setApiKey,
        account, setAccount,
        baseUrl, setBaseUrl,
        org, setOrg,
        validateResult, setValidateResult,
        installState, setInstallState,
        showAdvanced, setShowAdvanced,
        deviceLoginState, setDeviceLoginState,
        cliAuthStatus, setCliAuthStatus,
        cliAuthLoading, setCliAuthLoading,
        recommendation, setRecommendation,
        loadingRecommendation, setLoadingRecommendation,
    } = useProviderSettingsState();
    const { addToast } = useToast();
    const [providerHealthMap, setProviderHealthMap] = useState<Record<string, string>>({});

    const providerTypes = Object.keys(providerCapabilities);
    const providerTypeOptions = useMemo(() => {
        const known = KNOWN_PROVIDER_TYPES.filter((ptype) => providerTypes.includes(ptype));
        const missingKnown = KNOWN_PROVIDER_TYPES.filter((ptype) => !known.includes(ptype));
        const extra = providerTypes.filter((ptype) => !KNOWN_PROVIDER_TYPES.includes(ptype));
        return [...known, ...missingKnown, ...extra];
    }, [providerTypes]);

    const catalog = catalogs[providerType];
    const isLoadingCatalog = Boolean(catalogLoading[providerType]);
    const authModes = catalog?.auth_modes_supported || providerCapabilities[providerType]?.auth_modes_supported || [];
    const supportsInstall = (catalog?.install_method as string) === 'local_runtime';
    const accountModeRelevantProvider = providerType === 'codex' || providerType === 'claude';
    const accountModeAvailable = authModes.includes('account') || accountModeRelevantProvider;
    const effectiveHealth = validateResult?.health || effectiveState?.health || 'unknown';
    const effectiveActionableError = validateResult?.error_actionable || effectiveState?.last_error_actionable || 'sin errores recientes';

    const roleLabel = useMemo(() => {
        if (roles?.orchestrator?.provider_id) {
            return `orchestrator + ${roles.workers?.length || 0} workers`;
        }
        const active = providers.find((p) => p.id === effectiveState?.active);
        if (!active) return 'unknown';
        return active.is_local ? 'local' : 'remote';
    }, [providers, effectiveState, roles]);

    const modelGroups = useMemo(() => {
        const installed = catalog?.installed_models || [];
        const installedIds = new Set(installed.map((m: any) => m.id));
        const available = (catalog?.available_models || []).filter((m: any) => !installedIds.has(m.id));
        const recommended = (catalog?.recommended_models || []).filter((m: any) => !installedIds.has(m.id));
        return { installed, available, recommended };
    }, [catalog]);

    const filteredProviderTypeOptions = useMemo(() => {
        const q = providerSearch.trim().toLowerCase();
        if (!q) return providerTypeOptions;
        return providerTypeOptions.filter((ptype) => {
            const label = (PROVIDER_LABELS[ptype] || ptype).toLowerCase();
            return ptype.toLowerCase().includes(q) || label.includes(q);
        });
    }, [providerTypeOptions, providerSearch]);

    const healthBadgeClass = useMemo(() => {
        const health = String(effectiveHealth || '').toLowerCase();
        if (health === 'ok') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
        if (health === 'degraded') return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
        if (health === 'down') return 'bg-red-500/15 text-red-300 border-red-500/30';
        return 'bg-surface-3 text-text-secondary border-border-primary';
    }, [effectiveHealth]);

    const renderModelMeta = useCallback((m: any) => {
        const caps = Array.isArray(m?.capabilities) ? m.capabilities : [];
        const capText = caps.length ? `Excelente en: ${caps.join(', ')}` : null;
        const weakness = m?.weakness ? `Debilidad: ${m.weakness}` : null;
        const context = typeof m?.context_window === 'number' ? `${m.context_window.toLocaleString()} ctx` : null;
        const pieces = [capText, weakness, context].filter(Boolean);
        return pieces.length ? pieces.join(' | ') : (m?.description || 'Sin metadata adicional');
    }, []);

    useEffect(() => {
        if (effectiveState?.active && effectiveState?.health) {
            setProviderHealthMap(prev => ({ ...prev, [effectiveState.active]: effectiveState.health }));
        }
    }, [effectiveState?.active, effectiveState?.health]);

    const handleTestWithHealthUpdate = useCallback(async (id: string) => {
        const result = await testProvider(id);
        setProviderHealthMap(prev => ({ ...prev, [id]: result.healthy ? 'ok' : 'down' }));
        return result;
    }, [testProvider]);

    useEffect(() => {
        loadProviders();
        let mounted = true;
        const fetchRec = async () => {
            try {
                const res = await fetchWithRetry(`${API_BASE}/ops/provider/recommendation`, { credentials: 'include' });
                if (res.ok && mounted) {
                    setRecommendation(await res.json());
                }
            } catch (e) {
                console.error(e);
            } finally {
                if (mounted) setLoadingRecommendation(false);
            }
        };
        fetchRec();
        return () => { mounted = false; };
    }, []);

    useEffect(() => {
        if (providerTypeOptions.length > 0 && !providerTypeOptions.includes(providerType)) {
            setProviderType(providerTypeOptions[0]);
        }
    }, [providerTypeOptions, providerType]);

    useEffect(() => {
        if (!providerType) return;
        loadCatalog(providerType).catch(() => addToast('No se pudo cargar el catálogo de modelos', 'error'));
        if (!providerId) setProviderId(`${providerType}-main`);
        if (providerType === 'custom_openai_compatible' || providerType === 'cloudflare-workers-ai') {
            setShowAdvanced(true);
        } else {
            setShowAdvanced(false);
        }
    }, [providerType]);

    useEffect(() => {
        if (!catalog) return;
        if (!modelId) {
            const first = catalog.installed_models[0]?.id || catalog.recommended_models[0]?.id || catalog.available_models[0]?.id || '';
            setModelId(first);
        }
        if ((providerType === 'codex' || providerType === 'claude') && authModes.includes('account') && authMode !== 'account') {
            setAuthMode('account');
            return;
        }
        if (!authModes.includes(authMode)) {
            setAuthMode(authModes[0] || 'none');
        }
    }, [catalog]);

    const selectedModelInstalados = modelGroups.installed.some((m) => m.id === modelId);

    const handleInstallAndUse = useCallback(async (explicitModelId?: string) => {
        const targetModel = explicitModelId || modelId;
        if (!targetModel) {
            addToast('Selecciona un modelo para instalar', 'error');
            return;
        }
        try {
            const res = await installModel(providerType, targetModel);
            setInstallState(res);
            addToast(res?.message || 'Instalación lanzada', 'info');
        } catch {
            addToast('Error instalando el modelo', 'error');
        }
    }, [modelId, providerType, installModel, addToast]);

    const handleInstallCliDependency = useCallback(async (dependencyId: string) => {
        try {
            const res = await installCliDependency(dependencyId);
            setInstallState({ ...res, is_cli: true, dependency_id: dependencyId });
            addToast(res?.message || 'Instalación de CLI lanzada', 'info');
        } catch (err: any) {
            addToast(err.message || 'Error iniciando instalación', 'error');
        }
    }, [installCliDependency, addToast]);

    useEffect(() => {
        if (!installState?.job_id) return;
        if (!['queued', 'running'].includes(installState.status)) return;
        let cancelled = false;
        const timer = setInterval(async () => {
            try {
                let next;
                if (installState.is_cli && installState.dependency_id) {
                    next = await getCliDependencyInstallJob(installState.dependency_id, installState.job_id!);
                    next = { ...next, is_cli: true, dependency_id: installState.dependency_id };
                } else {
                    next = await getInstallJob(providerType, installState.job_id!);
                }
                if (cancelled) return;
                setInstallState(next);
                if (next.status === 'done') {
                    addToast('Instalación completada correctamente', 'success');
                    clearInterval(timer);
                    setDeviceLoginState(null);
                }
                if (next.status === 'error') {
                    addToast(next.message || 'Error en la instalación', 'error');
                    clearInterval(timer);
                }
            } catch {
                if (!cancelled) {
                    addToast('Se perdió la conexión con el progreso de instalación', 'error');
                    clearInterval(timer);
                }
            }
        }, 1200);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [installState?.job_id, installState?.status, installState?.is_cli, installState?.dependency_id, providerType, getInstallJob, getCliDependencyInstallJob, setDeviceLoginState, addToast]);

    const handleTestConnection = async () => {
        try {
            const payload: any = {
                base_url: baseUrl || undefined,
                org: org || undefined,
            };
            if (authMode === 'api_key') payload.api_key = apiKey;
            if (authMode === 'account') payload.account = account;
            const result = await validateProvider(providerType, payload);
            setValidateResult(result);
            if (result.valid) {
                addToast('Conexión válida', 'success');
                if (result.effective_model) setModelId(result.effective_model);
            } else {
                addToast(result.error_actionable || 'Validación fallida', 'error');
            }
        } catch {
            addToast('No se pudo validar la conexión', 'error');
        }
    };

    useEffect(() => {
        if (authMode !== 'account') { setCliAuthStatus(null); return; }
        const provider = providerType === 'codex' ? 'codex' : providerType === 'claude' ? 'claude' : null;
        if (!provider || !fetchCliAuthStatus) { setCliAuthStatus(null); return; }
        setCliAuthLoading(true);
        fetchCliAuthStatus(provider)
            .then(setCliAuthStatus)
            .catch(() => setCliAuthStatus({ authenticated: false }))
            .finally(() => setCliAuthLoading(false));
    }, [authMode, providerType, fetchCliAuthStatus]);

    const handleCliLogout = async () => {
        const provider = providerType === 'codex' ? 'codex' : 'claude';
        try {
            await cliLogout(provider);
            setCliAuthStatus({ authenticated: false });
            setDeviceLoginState(null);
            addToast(`Sesión de ${provider === 'codex' ? 'Codex' : 'Claude'} cerrada`, 'info');
        } catch {
            addToast('Error al cerrar sesión', 'error');
        }
    };

    const handleOAuthLikeLogin = async () => {
        try {
            setDeviceLoginState({ status: 'starting', message: 'Preparando autenticación segura...' });
            const data = await startCodexDeviceLogin();
            setDeviceLoginState(data);
            if (data.status === 'pending') {
                if (data.user_code && navigator.clipboard) {
                    try {
                        await navigator.clipboard.writeText(data.user_code);
                        addToast('Código copiado al portapapeles', 'success');
                    } catch (e) {
                        console.error('No se pudo copiar el código', e);
                    }
                }
                if (data.verification_url) {
                    window.open(data.verification_url, '_blank', 'noopener,noreferrer');
                }
            }
        } catch (err: any) {
            setDeviceLoginState({ status: 'error', message: err.message || 'Error al iniciar flujo', action: err?.action });
            addToast('Error al conectar cuenta OpenAI', 'error');
        }
    };

    const handleClaudeLogin = async () => {
        try {
            setDeviceLoginState({ status: 'starting', message: 'Abriendo navegador para autenticación con Anthropic...' });
            const data = await startClaudeLogin();
            setDeviceLoginState(data);
        } catch (err: any) {
            setDeviceLoginState({ status: 'error', message: err.message || 'Error al iniciar flujo de Claude', action: err?.action });
            addToast('Error al conectar cuenta Anthropic', 'error');
        }
    };

    const handleSaveAsActive = useCallback(async (overrides?: { providerId?: string; modelId?: string; authMode?: string; roleTarget?: 'orchestrator' | 'worker' }) => {
        const effectiveProviderId = overrides?.providerId || providerId;
        const effectiveModelId = overrides?.modelId || modelId;
        const effectiveAuthMode = overrides?.authMode || authMode;
        const roleTarget = overrides?.roleTarget || 'orchestrator';
        if (!effectiveProviderId.trim() || !effectiveModelId.trim()) {
            addToast('Provider ID y modelo son obligatorios', 'error');
            return;
        }
        try {
            await saveActiveProvider({
                providerId: effectiveProviderId.trim(),
                providerType: providerType,
                modelId: effectiveModelId.trim(),
                authMode: effectiveAuthMode,
                roleTarget,
                apiKey: effectiveAuthMode === 'api_key' ? apiKey : undefined,
                account: effectiveAuthMode === 'account' ? account : undefined,
                baseUrl: baseUrl || undefined,
                org: org || undefined,
            });
            addToast('Provider activo guardado', 'success');
            if (effectiveAuthMode === 'account' && (providerType === 'codex' || providerType === 'claude')) {
                setDeviceLoginState(null);
            }
        } catch {
            addToast('No se pudo guardar provider activo', 'error');
        }
    }, [providerId, modelId, authMode, providerType, apiKey, account, baseUrl, org, saveActiveProvider, addToast]);

    const applyRecommendation = useCallback(() => {
        if (!recommendation) return;
        const orchestratorReco = recommendation.orchestrator || { provider: recommendation.provider, model: recommendation.model };
        setProviderType(orchestratorReco.provider);
        setModelId(orchestratorReco.model);
        setProviderId(`${orchestratorReco.provider}-main`);
        setAuthMode('none');
        addToast(`Configuración sugerida aplicada: ${orchestratorReco.provider} - ${orchestratorReco.model}. Haz clic en Guardar Configuración.`, 'success');
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    }, [recommendation, addToast]);

    const renderAuthSection = () => {
        if (authMode === 'account' && providerType === 'codex') {
            return (
                <CodexAuthSection
                    cliAuthStatus={cliAuthStatus}
                    cliAuthLoading={cliAuthLoading}
                    deviceLoginState={deviceLoginState}
                    installState={installState}
                    account={account}
                    onLogin={handleOAuthLikeLogin}
                    onLogout={handleCliLogout}
                    onInstallCli={handleInstallCliDependency}
                    onCancelDeviceLogin={() => setDeviceLoginState(null)}
                    onCopyCode={() => {
                        if (navigator.clipboard && deviceLoginState?.user_code) {
                            navigator.clipboard.writeText(deviceLoginState.user_code);
                            addToast('Copiado manualmente', 'info');
                        }
                    }}
                    addToast={addToast}
                />
            );
        }
        if (authMode === 'account' && providerType === 'claude') {
            return (
                <ClaudeAuthSection
                    cliAuthStatus={cliAuthStatus}
                    cliAuthLoading={cliAuthLoading}
                    deviceLoginState={deviceLoginState}
                    installState={installState}
                    account={account}
                    onLogin={handleClaudeLogin}
                    onLogout={handleCliLogout}
                    onInstallCli={handleInstallCliDependency}
                    onCancelDeviceLogin={() => setDeviceLoginState(null)}
                />
            );
        }
        if (authMode === 'account') {
            return (
                <Input id="accountInput" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Session token o identificador..." className="bg-surface-0 border-border-primary text-text-primary w-full p-2.5 rounded-lg shadow-sm" />
            );
        }
        return (
            <Input id="apiKeyInput" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." className="bg-surface-0 border-border-primary text-text-primary w-full p-2.5 rounded-lg shadow-sm" />
        );
    };

    return (
        <div className="space-y-6 text-text-primary p-4">
            <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold flex items-center gap-2">
                    <Server className="w-5 h-5 text-indigo-400" />
                    Configuración de Providers
                </h2>
            </div>

            {!loadingRecommendation && recommendation && (
                <Card className="bg-surface-2 border-indigo-500/50 p-4 border shadow-[0_0_15px_rgba(99,102,241,0.1)] relative overflow-hidden">
                    <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500"></div>
                    <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                        <div>
                            <h3 className="text-sm font-bold text-white flex items-center gap-2 mb-1">
                                <Cpu className="w-4 h-4 text-indigo-400" /> Intelligent Auto-Config
                            </h3>
                            <p className="text-xs text-text-secondary">
                                Hardware detectado: {recommendation.hardware?.gpu_vendor && recommendation.hardware.gpu_vendor !== 'none' ? `${recommendation.hardware.gpu_vendor.toUpperCase()} GPU (${recommendation.hardware.gpu_vram_gb}GB VRAM)` : 'Sin GPU dedicada'}, RAM: {recommendation.hardware?.total_ram_gb}GB
                                {recommendation.hardware?.npu_vendor && recommendation.hardware.npu_vendor !== 'none' && (
                                    <span className="ml-1 text-indigo-300">· NPU: {recommendation.hardware.npu_name} ({recommendation.hardware.npu_tops} TOPS)</span>
                                )}
                            </p>
                            <p className="text-xs text-indigo-200 mt-2 font-medium">
                                Recomendación: {recommendation.orchestrator?.provider || recommendation.provider} ({recommendation.orchestrator?.model || recommendation.model})
                                {' '}con {recommendation.worker_pool?.[0]?.count_hint || recommendation.workers} workers.
                            </p>
                            {recommendation.scoring && (
                                <div className="flex items-center gap-3 mt-1">
                                    <div className="flex items-center gap-1">
                                        <div className="w-16 h-1.5 rounded-full bg-surface-0 overflow-hidden">
                                            <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, recommendation.scoring.total)}%` }} />
                                        </div>
                                        <span className="text-[10px] text-indigo-300">{recommendation.scoring.total}/100</span>
                                    </div>
                                    <span className="text-[10px] text-text-secondary">{recommendation.scoring.tier_label}</span>
                                    {recommendation.scoring.bottleneck && (
                                        <span className="text-[10px] text-amber-400">⚠ {recommendation.scoring.bottleneck}</span>
                                    )}
                                </div>
                            )}
                            <p className="text-[10px] text-text-secondary mt-0.5">Motivo: {recommendation.topology_reason || recommendation.reason}</p>
                        </div>
                        <Button onClick={applyRecommendation} className="bg-indigo-600 hover:bg-indigo-500 text-white shrink-0 text-xs">
                            Aplicar Configuración
                        </Button>
                    </div>
                </Card>
            )}

            <Card className="bg-surface-2 border-border-primary p-4">
                <h3 className="text-sm font-semibold mb-3 text-text-secondary uppercase tracking-wider">Estado efectivo actual</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                    <div><span className="text-text-secondary">Provider activo:</span> <span className="font-semibold">{effectiveState?.active || 'n/a'}</span></div>
                    <div><span className="text-text-secondary">Modelo efectivo:</span> <span className="font-semibold">{effectiveState?.model_id || 'n/a'}</span></div>
                    <div><span className="text-text-secondary">Rol:</span> <span className="font-semibold">{roleLabel}</span></div>
                    <div>
                        <span className="text-text-secondary mr-2">Salud:</span>
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs border ${healthBadgeClass}`}>
                            {effectiveHealth}
                        </span>
                    </div>
                    <div className="md:col-span-2"><span className="text-text-secondary">Error accionable:</span> <span className="font-semibold text-accent-warning">{effectiveActionableError}</span></div>
                </div>
            </Card>

            <Card className="bg-surface-2 border-border-primary p-5 overflow-hidden">
                <h3 className="text-sm font-semibold mb-5 flex items-center gap-2">
                    <Server className="w-4 h-4 text-indigo-400" />
                    Ajustes de Conexión
                </h3>
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_240px] gap-6 items-start">
                <div className="flex flex-col gap-6">
                    <div className="max-w-xl">
                        <label className="block text-sm font-medium text-text-primary mb-2">Proveedor API</label>
                        <div className="relative">
                            <button
                                type="button"
                                onClick={() => setProviderDropdownOpen((v) => !v)}
                                className="w-full bg-surface-0 border border-border-primary rounded-lg p-2.5 text-sm text-text-primary text-left focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all shadow-sm"
                            >
                                {PROVIDER_LABELS[providerType] || providerType}
                            </button>
                            {providerDropdownOpen && (
                                <div className="absolute z-30 mt-2 w-full bg-surface-1 border border-border-primary rounded-lg shadow-xl p-2">
                                    <Input
                                        autoFocus
                                        value={providerSearch}
                                        onChange={(e) => setProviderSearch(e.target.value)}
                                        placeholder="Buscar provider dentro del dropdown..."
                                        className="mb-2 bg-surface-0 border-border-primary text-text-primary"
                                    />
                                    <div className="max-h-64 overflow-auto">
                                        {filteredProviderTypeOptions.map((canonical) => (
                                            <button
                                                key={canonical}
                                                type="button"
                                                onClick={() => {
                                                    setProviderType(canonical);
                                                    setProviderId(`${canonical}-main`);
                                                    setModelId('');
                                                    setValidateResult(null);
                                                    if (canonical === 'codex' || canonical === 'claude') {
                                                        setAuthMode('account');
                                                    }
                                                    setProviderDropdownOpen(false);
                                                }}
                                                className={`w-full text-left px-2 py-1.5 text-sm rounded ${providerType === canonical ? 'bg-indigo-500/20 text-indigo-200' : 'hover:bg-surface-2 text-text-primary'}`}
                                            >
                                                {PROVIDER_LABELS[canonical] || canonical}
                                            </button>
                                        ))}
                                        {filteredProviderTypeOptions.length === 0 && (
                                            <div className="px-2 py-2 text-xs text-text-secondary">Sin resultados</div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {providerType === 'ollama_local' ? (
                        <div className="col-span-full mt-4">
                            <OllamaLocalSection
                                catalog={catalog}
                                modelGroups={modelGroups}
                                isLoadingCatalog={isLoadingCatalog}
                                modelId={modelId}
                                onModelIdChange={setModelId}
                                onAssignOrchestrator={(mId) => {
                                    setProviderId('ollama-main');
                                    setModelId(mId);
                                    setAuthMode('none');
                                    void handleSaveAsActive({ providerId: 'ollama-main', modelId: mId, authMode: 'none', roleTarget: 'orchestrator' });
                                }}
                                onAddWorker={async (mId) => {
                                    try {
                                        await saveActiveProvider({
                                            providerId: `ollama-worker-${mId.split(':')[0]}`,
                                            providerType: 'ollama_local',
                                            modelId: mId,
                                            authMode: 'none',
                                            roleTarget: 'worker',
                                        });
                                        const label = modelGroups.installed.find(m => m.id === mId)?.label || mId;
                                        addToast(`Worker ${label} enrolado`, 'success');
                                    } catch {
                                        addToast(`Error al añadir Worker`, 'error');
                                    }
                                }}
                                onInstallModel={handleInstallAndUse}
                                addToast={addToast}
                            />
                        </div>
                    ) : (
                        <div className="flex flex-col gap-5 col-span-full max-w-xl">
                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-text-primary">Autenticación</label>
                                {renderAuthSection()}
                                {providerType === 'cloudflare-workers-ai' && (
                                    <div className="rounded-lg border border-border-primary bg-surface-1 px-3 py-2 text-[11px] text-text-secondary">
                                        Cloudflare Workers AI usa el endpoint OpenAI-compatible con <code>account_id</code> embebido en la URL.
                                        Configura la Base URL como <code>https://api.cloudflare.com/client/v4/accounts/&lt;ACCOUNT_ID&gt;/ai/v1</code>
                                        y usa un token con <code>Workers AI - Read</code> y <code>Workers AI - Edit</code>.
                                    </div>
                                )}
                                {authMode === 'api_key' && <div className="text-[11px] text-text-secondary px-1">La clave se enviará de forma segura al orquestador.</div>}
                            </div>

                            <div className="space-y-2">
                                <label htmlFor="modelIdSelect" className="block text-sm font-medium text-text-primary">Modelo</label>
                                <ModelSelector
                                    modelId={modelId}
                                    modelGroups={modelGroups}
                                    isLoading={isLoadingCatalog}
                                    supportsInstall={supportsInstall}
                                    modelSearch={modelSearch}
                                    modelDropdownOpen={modelDropdownOpen}
                                    onSelect={(id) => { setModelId(id); setModelDropdownOpen(false); }}
                                    onSearchChange={setModelSearch}
                                    onToggleDropdown={() => setModelDropdownOpen((v) => !v)}
                                    renderModelMeta={renderModelMeta}
                                />
                            </div>

                            <div className="mt-2 border border-border-primary rounded-lg overflow-hidden bg-surface-1">
                                <button
                                    onClick={() => setShowAdvanced(!showAdvanced)}
                                    className="w-full text-xs text-text-secondary hover:text-text-primary transition-colors flex items-center justify-between font-medium p-3 bg-surface-2 hover:bg-surface-3"
                                >
                                    <span className="uppercase tracking-wider font-semibold">Opciones Avanzadas</span>
                                    <span className="text-[10px]">{showAdvanced ? 'OCULTAR ▲' : 'MOSTRAR ▼'}</span>
                                </button>
                                {showAdvanced && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 border-t border-border-primary bg-surface-0">
                                        <div>
                                            <label htmlFor="providerIdInput" className="block text-xs text-text-secondary mb-1">Nombre Conexión (ID Interno)</label>
                                            <Input id="providerIdInput" value={providerId} onChange={(e) => setProviderId(e.target.value)} className="bg-surface-1 border-border-primary text-text-primary text-sm rounded" />
                                        </div>
                                        <div>
                                            <label htmlFor="authModeSelect" className="block text-xs text-text-secondary mb-1">Modo Auth (Forzado)</label>
                                            <select
                                                id="authModeSelect"
                                                value={authMode}
                                                onChange={(e) => setAuthMode(e.target.value)}
                                                className="w-full bg-surface-1 border border-border-primary rounded p-2 text-sm text-text-primary"
                                            >
                                                {authModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
                                                {authModes.length === 0 && <option value="none">none</option>}
                                            </select>
                                        </div>
                                        <div>
                                            <label htmlFor="baseUrlInput" className="block text-xs text-text-secondary mb-1">Base URL Personalizada</label>
                                            <Input id="baseUrlInput" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://.../v1" className="bg-surface-1 border-border-primary text-text-primary text-sm rounded" />
                                            {providerType === 'cloudflare-workers-ai' && (
                                                <div className="mt-1 text-[10px] text-text-secondary">
                                                    Ejemplo: <code>https://api.cloudflare.com/client/v4/accounts/&lt;ACCOUNT_ID&gt;/ai/v1</code>
                                                </div>
                                            )}
                                        </div>
                                        <div>
                                            <label htmlFor="orgInput" className="block text-xs text-text-secondary mb-1">Organization ID</label>
                                            <Input id="orgInput" value={org} onChange={(e) => setOrg(e.target.value)} className="bg-surface-1 border-border-primary text-text-primary text-sm rounded" />
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="flex flex-col sm:flex-row items-center justify-end gap-3 pt-6">
                                <Button onClick={handleTestConnection} variant="ghost" className="w-full sm:w-auto text-text-secondary hover:text-text-primary border border-border-primary hover:bg-surface-3 rounded-lg px-6">
                                    Probar conexión
                                </Button>
                                <Button onClick={() => void handleSaveAsActive()} className="w-full sm:w-auto bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg px-8 shadow-md">
                                    Guardar Configuración
                                </Button>
                            </div>
                        </div>
                    )}

                {catalog?.warnings?.length ? (
                    <div className="mt-3 text-xs text-accent-warning space-y-1">
                        {catalog.warnings.map((w: string, idx: number) => <div key={`${w}-${idx}`}>⚠ {w}</div>)}
                    </div>
                ) : null}

                {accountModeAvailable || !accountModeRelevantProvider ? null : (
                    <div className="mt-3 text-xs text-accent-warning">Modo cuenta no disponible en este entorno; usa API key.</div>
                )}

                {!selectedModelInstalados && supportsInstall && modelId ? (
                    <div className="mt-4 p-3 rounded border border-border-primary bg-surface-0 flex items-center justify-between gap-3">
                        <div className="text-xs text-text-primary">Modelo no instalado. ¿Quieres descargarlo ahora?</div>
                        <Button onClick={() => void handleInstallAndUse()} className="bg-accent-primary hover:bg-accent-primary/80 text-white text-xs px-3 py-2">
                            Descargar y usar
                        </Button>
                    </div>
                ) : null}

                {installState ? (
                    <div className="mt-3 p-3 rounded border border-border-primary bg-surface-0">
                        <div className="text-xs text-text-primary">Instalación: {installState.status}</div>
                        <div className="text-xs text-text-secondary">{installState.message}</div>
                        {typeof installState.progress === 'number' ? (
                            <div className="text-xs text-text-secondary">Progreso: {Math.round(installState.progress * 100)}%</div>
                        ) : null}
                    </div>
                ) : null}

                {validateResult ? (
                    <div className={`mt-4 p-3 rounded border ${validateResult.valid ? 'border-accent-trust/40 bg-accent-trust/10' : 'border-accent-alert/40 bg-accent-alert/10'}`}>
                        <div className="flex items-center gap-2 text-sm">
                            {validateResult.valid ? <CheckCircle2 className="w-4 h-4 text-accent-trust" /> : <AlertTriangle className="w-4 h-4 text-accent-alert" />}
                            <span>{validateResult.valid ? 'Conexión válida' : 'Conexión no válida'}</span>
                            <span className="text-xs text-text-secondary">health: {validateResult.health}</span>
                        </div>
                        {validateResult.error_actionable ? <div className="mt-2 text-xs">Acción sugerida: {validateResult.error_actionable}</div> : null}
                    </div>
                ) : null}
                </div>

                {/* ── Provider status sidebar ─────────────────────────────── */}
                <div className="hidden lg:flex flex-col gap-1 border-l border-border-primary pl-5 pt-0.5">
                    <h4 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wider mb-2">Providers configurados</h4>
                    {providers.length === 0 ? (
                        <p className="text-xs text-text-secondary italic">Sin providers guardados.</p>
                    ) : (
                        providers.map((p) => {
                            const rawHealth = providerHealthMap[p.id] ?? (p.id === effectiveState?.active ? effectiveState?.health : 'unknown');
                            const health = String(rawHealth || 'unknown').toLowerCase();
                            const dotClass =
                                health === 'ok'
                                    ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]'
                                    : health === 'degraded'
                                    ? 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.8)]'
                                    : health === 'down'
                                    ? 'bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.7)]'
                                    : 'bg-surface-3 animate-pulse';
                            const statusLabel =
                                health === 'ok' ? 'OK'
                                : health === 'degraded' ? 'Reconectando'
                                : health === 'down' ? 'Desconectado'
                                : '—';
                            return (
                                <button
                                    key={p.id}
                                    type="button"
                                    onClick={() => {
                                        setProviderType(p.type);
                                        setProviderId(p.id);
                                        setModelId(p.model || p.config?.model || '');
                                    }}
                                    title={`Seleccionar ${p.config?.display_name || p.id} • Estado: ${statusLabel}`}
                                    className={`flex items-center gap-2.5 py-2 px-2 rounded-lg text-left transition-colors hover:bg-surface-3/60 w-full group ${providerType === p.type && providerId === p.id ? 'bg-indigo-500/10 ring-1 ring-indigo-500/30' : ''}`}
                                >
                                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass}`} />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-medium text-text-primary truncate leading-tight">
                                            {p.config?.display_name || PROVIDER_LABELS[p.type] || p.id}
                                        </div>
                                        <div className="text-[10px] text-text-secondary truncate leading-tight">
                                            {p.model || p.config?.model || 'modelo n/a'}
                                        </div>
                                    </div>
                                    {p.id === effectiveState?.active && (
                                        <span className="text-[9px] text-indigo-400 font-semibold uppercase tracking-wide flex-shrink-0">activo</span>
                                    )}
                                </button>
                            );
                        })
                    )}
                    {providers.length > 0 && (
                        <p className="text-[10px] text-text-secondary mt-2 px-2">
                            Haz clic en un provider para editar su configuración.
                        </p>
                    )}
                </div>
                </div>
            </Card>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.entries(nodes).map(([id, node]: [string, any]) => (
                    <Card key={id} className="bg-surface-2/70 border-border-primary p-3">
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-semibold text-sm flex items-center gap-2">
                                {id === 'ally_x' ? <Cpu className="w-4 h-4 text-emerald-400" /> : <Server className="w-4 h-4 text-blue-400" />}
                                {node.name}
                            </span>
                            <span className="text-xs text-text-secondary">{node.type}</span>
                        </div>
                        <div className="w-full bg-surface-0 h-2 rounded-full overflow-hidden">
                            <div
                                className={`h-full transition-all duration-500 ${node.current_load >= node.max_concurrency ? 'bg-red-500' : 'bg-emerald-500'}`}
                                style={{ width: `${(node.current_load / node.max_concurrency) * 100}%` }}
                            />
                        </div>
                        <div className="flex justify-between mt-1 text-xs text-text-secondary">
                            <span>Carga: {node.current_load} / {node.max_concurrency} agentes</span>
                            <span>{node.current_load >= node.max_concurrency ? 'LLENO' : 'DISPONIBLE'}</span>
                        </div>
                    </Card>
                ))}
            </div>

            <ProviderList
                providers={providers}
                onTest={handleTestWithHealthUpdate}
                onRemove={removeProvider}
                addToast={addToast}
            />
        </div>
    );
};
