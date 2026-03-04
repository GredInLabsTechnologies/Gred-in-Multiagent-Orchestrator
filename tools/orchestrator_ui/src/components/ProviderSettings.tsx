import React, { useMemo, useState, useEffect, useCallback } from 'react';
import { Card } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { useProviders } from '../hooks/useProviders';
import { useToast } from './Toast';
import { Server, Cloud, Cpu, Trash2, Activity, Download, CheckCircle2, AlertTriangle } from 'lucide-react';

/* ── Friendly provider type labels ── */
const PROVIDER_LABELS: Record<string, string> = {
    openai: 'OpenAI',
    codex: 'Codex CLI',
    claude: 'Anthropic (Claude CLI)',
    ollama_local: 'Ollama (Local)',
    groq: 'Groq',
    openrouter: 'OpenRouter',
    custom_openai_compatible: 'OpenAI Compatible',
};

export const ProviderSettings: React.FC = () => {
    const {
        providers,
        providerCapabilities,
        effectiveState,
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
    } = useProviders();
    const { addToast } = useToast();

    const [providerType, setProviderType] = useState('openai');
    const [providerId, setProviderId] = useState('openai-main');
    const [modelId, setModelId] = useState('');
    const [authMode, setAuthMode] = useState('api_key');
    const [apiKey, setApiKey] = useState('');
    const [account, setAccount] = useState('');
    const [baseUrl, setBaseUrl] = useState('');
    const [org, setOrg] = useState('');
    const [validateResult, setValidateResult] = useState<any>(null);
    const [installState, setInstallState] = useState<{ status: string; message: string; progress?: number; job_id?: string } | null>(null);
    const [showAdvanced, setShowAdvanced] = useState(false);

    // Codex device flow state
    const [deviceLoginState, setDeviceLoginState] = useState<{ status: string; verification_url?: string; user_code?: string; message?: string } | null>(null);

    // Merge dynamic types from backend with standard hardcoded types to ensure they always show up
    const backendTypes = Object.keys(providerCapabilities);
    const standardTypes = ['openai', 'codex', 'claude', 'ollama_local', 'groq', 'openrouter', 'custom_openai_compatible'];
    const providerTypes = Array.from(new Set([...backendTypes, ...standardTypes]));

    const catalog = catalogs[providerType];
    const isLoadingCatalog = Boolean(catalogLoading[providerType]);
    const authModes = catalog?.auth_modes_supported || providerCapabilities[providerType]?.auth_modes_supported || [];
    const supportsInstall = Boolean(catalog?.can_install);
    const accountModeRelevantProvider = providerType === 'codex' || providerType === 'claude';
    const accountModeAvailable = authModes.includes('account') || accountModeRelevantProvider;
    const effectiveHealth = validateResult?.health || effectiveState?.health || 'unknown';
    const effectiveActionableError = validateResult?.error_actionable || effectiveState?.last_error_actionable || 'sin errores recientes';
    const roleLabel = useMemo(() => {
        const active = providers.find((p) => p.id === effectiveState?.active);
        if (!active) return 'unknown';
        return active.is_local ? 'local' : 'remote';
    }, [providers, effectiveState]);

    const modelGroups = useMemo(() => {
        const installed = catalog?.installed_models || [];
        const available = catalog?.available_models || [];
        const recommended = catalog?.recommended_models || [];
        return { installed, available, recommended };
    }, [catalog]);

    useEffect(() => {
        loadProviders();
    }, []);

    useEffect(() => {
        if (providerTypes.length > 0 && !providerTypes.includes(providerType)) {
            setProviderType(providerTypes[0]);
        }
    }, [providerTypes, providerType]);

    useEffect(() => {
        if (!providerType) return;
        loadCatalog(providerType).catch(() => addToast('No se pudo cargar el catálogo de modelos', 'error'));
        if (!providerId) setProviderId(`${providerType}-main`);
        if (providerType === 'custom_openai_compatible') {
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

    useEffect(() => {
        if (!installState?.job_id) return;
        if (!['queued', 'running'].includes(installState.status)) return;
        let cancelled = false;
        const timer = setInterval(async () => {
            try {
                const next = await getInstallJob(providerType, installState.job_id!);
                if (cancelled) return;
                setInstallState(next);
                if (next.status === 'done') {
                    addToast('Modelo instalado correctamente', 'success');
                    clearInterval(timer);
                }
                if (next.status === 'error') {
                    addToast(next.message || 'Error instalando modelo', 'error');
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
    }, [installState?.job_id, installState?.status, providerType]);

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

    const handleOAuthLikeLogin = async () => {
        try {
            setDeviceLoginState({ status: 'starting', message: 'Preparando autenticación segura...' });
            const data = await startCodexDeviceLogin();
            setDeviceLoginState(data);

            if (data.status === 'pending') {
                if (!account) {
                    setAccount('codex-device-session');
                }

                // Copy to clipboard automatically if possible
                if (data.user_code && navigator.clipboard) {
                    try {
                        await navigator.clipboard.writeText(data.user_code);
                        addToast('Código copiado al portapapeles', 'success');
                    } catch (e) {
                        console.error('No se pudo copiar el código', e);
                    }
                }

                // Open window automatically
                if (data.verification_url) {
                    window.open(data.verification_url, '_blank', 'noopener,noreferrer');
                }
            }
        } catch (err: any) {
            setDeviceLoginState({ status: 'error', message: err.message || 'Error al iniciar flujo' });
            addToast('Error al conectar cuenta OpenAI', 'error');
        }
    };

    const handleClaudeLogin = async () => {
        try {
            setDeviceLoginState({ status: 'starting', message: 'Abriendo navegador para autenticación con Anthropic...' });
            const data = await startClaudeLogin();
            setDeviceLoginState(data);

            if (data.status === 'pending') {
                if (!account) {
                    setAccount('claude-device-session');
                }
            }
        } catch (err: any) {
            setDeviceLoginState({ status: 'error', message: err.message || 'Error al iniciar flujo de Claude' });
            addToast('Error al conectar cuenta Anthropic', 'error');
        }
    };

    const handleSaveAsActive = useCallback(async (overrides?: { providerId?: string; modelId?: string; authMode?: string }) => {
        const effectiveProviderId = overrides?.providerId || providerId;
        const effectiveModelId = overrides?.modelId || modelId;
        const effectiveAuthMode = overrides?.authMode || authMode;
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
                apiKey: effectiveAuthMode === 'api_key' ? apiKey : undefined,
                account: effectiveAuthMode === 'account' ? account : undefined,
                baseUrl: baseUrl || undefined,
                org: org || undefined,
            });
            addToast('Provider activo guardado', 'success');

            // Clean up UI states after successful save, specially for Device Login flows
            if (effectiveAuthMode === 'account' && (providerType === 'codex' || providerType === 'claude')) {
                setDeviceLoginState(null);
            }
        } catch {
            addToast('No se pudo guardar provider activo', 'error');
        }
    }, [providerId, modelId, authMode, providerType, apiKey, account, baseUrl, org, saveActiveProvider, addToast]);

    return (
        <div className="space-y-6 text-text-primary p-4">
            <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold flex items-center gap-2">
                    <Server className="w-5 h-5 text-indigo-400" />
                    Configuración de Providers
                </h2>
            </div>

            <Card className="bg-surface-2 border-border-primary p-4">
                <h3 className="text-sm font-semibold mb-3 text-text-secondary uppercase tracking-wider">Estado efectivo actual</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                    <div><span className="text-text-secondary">Provider activo:</span> <span className="font-semibold">{effectiveState?.active || 'n/a'}</span></div>
                    <div><span className="text-text-secondary">Modelo efectivo:</span> <span className="font-semibold">{effectiveState?.model_id || 'n/a'}</span></div>
                    <div><span className="text-text-secondary">Rol:</span> <span className="font-semibold">{roleLabel}</span></div>
                    <div><span className="text-text-secondary">Salud:</span> <span className="font-semibold">{effectiveHealth}</span></div>
                    <div className="md:col-span-2"><span className="text-text-secondary">Error accionable:</span> <span className="font-semibold text-accent-warning">{effectiveActionableError}</span></div>
                </div>
            </Card>

            <Card className="bg-surface-2 border-border-primary p-5 overflow-hidden">
                <h3 className="text-sm font-semibold mb-5 flex items-center gap-2">
                    <Server className="w-4 h-4 text-indigo-400" />
                    Ajustes de Conexión
                </h3>
                <div className="grid grid-cols-1 gap-6 items-start">
                    <div className="col-span-full max-w-xl">
                        <label className="block text-sm font-medium text-text-primary mb-2">Proveedor API</label>
                        <select
                            value={providerType}
                            onChange={(e) => {
                                setProviderType(e.target.value);
                                setProviderId(`${e.target.value}-main`);
                                setModelId('');
                                setValidateResult(null);
                            }}
                            className="w-full bg-surface-0 border border-border-primary rounded-lg p-2.5 text-sm text-text-primary focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all shadow-sm"
                        >
                            {(providerTypes.length > 0 ? providerTypes : ['openai', 'codex', 'claude', 'ollama_local', 'groq', 'openrouter', 'custom_openai_compatible']).map((canonical) => (
                                <option key={canonical} value={canonical}>{PROVIDER_LABELS[canonical] || canonical}</option>
                            ))}
                        </select>
                    </div>
                    {providerType === 'ollama_local' ? (
                        <div className="col-span-full mt-4 space-y-4">
                            {!catalog ? (
                                <div className="p-8 text-center bg-surface-0 rounded border border-border-primary text-text-secondary">
                                    {isLoadingCatalog ? 'Buscando servidor Ollama local...' : 'No se pudo conectar con Ollama.'}
                                </div>
                            ) : (
                                <>
                                    <div className="flex items-center justify-between mb-2">
                                        <div>
                                            <h4 className="text-sm font-semibold text-white">Modelos Detectados (Zero-Config)</h4>
                                            <p className="text-xs text-text-secondary">No necesitas API Keys. Selecciona un modelo para asignar su rol en el enjambre.</p>
                                        </div>
                                    </div>
                                    {modelGroups.installed.length === 0 ? (
                                        <div className="p-8 text-center bg-surface-0 rounded border border-border-primary text-text-secondary">
                                            Ollama está instalado, pero no tienes modelos descargados.
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                                            {modelGroups.installed.map(m => (
                                                <div key={m.id} className="p-3 bg-surface-0 border border-border-primary hover:border-surface-3 rounded-xl flex flex-col justify-between transition-colors">
                                                    <div>
                                                        <div className="font-semibold text-sm text-white truncate" title={m.label}>{m.label}</div>
                                                        <div className="text-[10px] text-text-secondary uppercase tracking-wider">{m.size || 'Desconocido'}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2 mt-4">
                                                        <Button
                                                            size="sm"
                                                            className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] h-7 px-2"
                                                            onClick={() => {
                                                                setProviderId('ollama-main');
                                                                setModelId(m.id);
                                                                setAuthMode('none');
                                                                void handleSaveAsActive({ providerId: 'ollama-main', modelId: m.id, authMode: 'none' });
                                                            }}
                                                        >
                                                            Asignar Orchestrator
                                                        </Button>
                                                        <Button
                                                            size="sm"
                                                            className="flex-1 bg-surface-3 hover:bg-surface-3 text-white text-[11px] h-7 px-2"
                                                            onClick={async () => {
                                                                try {
                                                                    await saveActiveProvider({
                                                                        providerId: `ollama-worker-${m.id.split(':')[0]}`,
                                                                        providerType: 'ollama_local',
                                                                        modelId: m.id,
                                                                        authMode: 'none',
                                                                    });
                                                                    addToast(`Worker ${m.label} enrolado`, 'success');
                                                                } catch {
                                                                    addToast(`Error al añadir Worker ${m.label}`, 'error');
                                                                }
                                                            }}
                                                        >
                                                            Añadir Worker
                                                        </Button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    <div className="mt-6 border-t border-border-primary pt-4">
                                        <h4 className="text-sm font-semibold text-white mb-2">Descargar Modelos (Pull)</h4>
                                        <p className="text-xs text-text-secondary mb-4">Descarga nuevos modelos directamente desde el registro de Ollama.</p>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            {modelGroups.recommended.filter((m: any) => !m.installed).map((m: any) => (
                                                <div key={m.id} className="p-3 bg-surface-2 border border-border-primary hover:border-surface-3 transition-colors rounded-xl flex items-center justify-between">
                                                    <div>
                                                        <div className="text-sm text-white font-medium">{m.label || m.id}</div>
                                                        <div className="text-xs text-text-secondary">{m.id}</div>
                                                    </div>
                                                    <Button
                                                        size="sm"
                                                        className="bg-surface-3 hover:bg-accent-primary hover:text-white transition-colors text-xs"
                                                        onClick={() => {
                                                            setModelId(m.id);
                                                            void handleInstallAndUse(m.id);
                                                        }}
                                                    >
                                                        <Download className="w-3.5 h-3.5 mr-1" />
                                                        Descargar
                                                    </Button>
                                                </div>
                                            ))}

                                            <div className="p-3 bg-surface-2 border border-border-primary rounded-xl flex flex-col justify-between">
                                                <div className="text-sm text-white font-medium mb-2">Otro Modelo...</div>
                                                <div className="flex items-center gap-2">
                                                    <Input
                                                        placeholder="ej: mistral:instruct"
                                                        className="h-8 text-xs bg-surface-0 border-border-primary text-white"
                                                        value={modelId}
                                                        onChange={(e) => setModelId(e.target.value)}
                                                    />
                                                    <Button
                                                        size="sm"
                                                        title="Descargar desde Ollama"
                                                        className="bg-surface-3 hover:bg-accent-primary hover:text-white transition-colors text-xs shrink-0 h-8 w-8 p-0 flex items-center justify-center"
                                                        onClick={() => {
                                                            if (modelId) void handleInstallAndUse();
                                                            else addToast('Escribe el tag del modelo', 'info');
                                                        }}
                                                    >
                                                        <Download className="w-4 h-4" />
                                                    </Button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    ) : (
                        <div className="flex flex-col gap-5 col-span-full max-w-xl">
                            {/* Authentication Section */}
                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-text-primary">Autenticación</label>
                                {authMode === 'account' && providerType === 'codex' ? (
                                    <div className="p-4 border border-border-primary rounded-lg bg-surface-1">
                                        {!deviceLoginState || deviceLoginState.status === 'error' ? (
                                            <div className="flex flex-col gap-3">
                                                <div>
                                                    <div className="text-sm font-medium">Cuenta de OpenAI (Suscripción Plus/Pro)</div>
                                                    <div className="text-xs text-text-secondary mt-1">Usa los modelos a los que ya tienes acceso sin pagar por token a través de API Keys.</div>
                                                    {deviceLoginState?.status === 'error' && (
                                                        <div className="mt-2 text-xs text-accent-alert bg-accent-alert/10 p-2 rounded">{deviceLoginState.message}</div>
                                                    )}
                                                </div>
                                                <Button onClick={handleOAuthLikeLogin} className="w-full bg-[#10a37f] hover:bg-[#0e906f] text-white flex items-center justify-center gap-2 shadow-md h-10 transition-colors">
                                                    Autenticar en OpenAI
                                                </Button>
                                                <div className="text-[10px] text-text-secondary flex justify-center mt-1">
                                                    Soporte nativo mediante OpenAI Codex CLI
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="space-y-4">
                                                <div className="flex items-center gap-2 bg-surface-2 p-2 rounded justify-between">
                                                    <div className="flex items-center gap-2">
                                                        <div className="w-2.5 h-2.5 rounded-full bg-[#10a37f] animate-pulse shadow-[0_0_8px_rgba(16,163,127,0.6)]"></div>
                                                        <p className="text-xs font-semibold text-[#10a37f] uppercase tracking-wider">Esperando Autorización...</p>
                                                    </div>
                                                </div>

                                                <div className="text-xs text-text-secondary">
                                                    {deviceLoginState.status === 'starting' ? (
                                                        <p className="animate-pulse">{deviceLoginState.message}</p>
                                                    ) : (
                                                        <div className="space-y-3">
                                                            <p className="text-sm text-text-primary">Sigue estos pasos para finalizar:</p>

                                                            <ol className="list-decimal list-inside space-y-2 ml-1">
                                                                <li>
                                                                    Ve a la ventana que acabamos de abrir (o entra a <a href={deviceLoginState.verification_url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:text-indigo-300 hover:underline">{deviceLoginState.verification_url}</a>).
                                                                </li>
                                                                <li className="flex flex-col gap-1 mt-2">
                                                                    <span>Pega este código de dispositivo allí:</span>
                                                                    <div className="flex items-center gap-2 mt-1">
                                                                        <span className="font-mono bg-surface-0 px-3 py-1.5 cursor-text rounded font-bold text-white tracking-widest text-lg border border-border-primary shadow-inner">
                                                                            {deviceLoginState.user_code}
                                                                        </span>
                                                                        <Button
                                                                            onClick={() => {
                                                                                if (navigator.clipboard && deviceLoginState.user_code) {
                                                                                    navigator.clipboard.writeText(deviceLoginState.user_code);
                                                                                    addToast('Copiado manualmente', 'info');
                                                                                }
                                                                            }}
                                                                            size="sm"
                                                                            variant="outline"
                                                                            className="h-8 border-border-primary bg-surface-2 hover:bg-surface-3 transition-colors text-xs"
                                                                            title="Copiar Código"
                                                                        >
                                                                            Copiar
                                                                        </Button>
                                                                    </div>
                                                                </li>
                                                                <li className="mt-2">Haz clic en "Confirmar".</li>
                                                            </ol>
                                                            <p className="mt-4 p-2 bg-indigo-500/10 border border-indigo-500/20 rounded text-indigo-200">
                                                                <strong>Nota:</strong> Una vez confirmado en el navegador, selecciona un `Modelo` abajo y presiona **"Guardar Configuración"**.
                                                            </p>
                                                        </div>
                                                    )}
                                                </div>

                                                <Button onClick={() => setDeviceLoginState(null)} size="sm" variant="ghost" className="w-full mt-4 text-xs text-text-secondary hover:text-text-primary border border-transparent hover:border-border-primary transition-all">
                                                    Cancelar y Reintentar
                                                </Button>
                                            </div>
                                        )}
                                        <input type="hidden" value={account} />
                                    </div>
                                ) : authMode === 'account' && providerType === 'claude' ? (
                                    <div className="p-4 border border-border-primary rounded-lg bg-surface-1">
                                        {!deviceLoginState || deviceLoginState.status === 'error' ? (
                                            <div className="flex flex-col gap-3">
                                                <div>
                                                    <div className="text-sm font-medium">Cuenta de Anthropic (Pro/Team)</div>
                                                    <div className="text-xs text-text-secondary mt-1">Usa tu sesión local de Claude (requiere claude CLI instalada).</div>
                                                    {deviceLoginState?.status === 'error' && (
                                                        <div className="mt-2 text-xs text-accent-alert bg-accent-alert/10 p-2 rounded">{deviceLoginState.message}</div>
                                                    )}
                                                </div>
                                                <Button onClick={handleClaudeLogin} className="w-full bg-[#d97757] hover:bg-[#b86246] text-white flex items-center justify-center gap-2 shadow-md h-10 transition-colors">
                                                    Autenticar en Anthropic
                                                </Button>
                                                <div className="text-[10px] text-text-secondary flex justify-center mt-1">
                                                    Abrirá el navegador automáticamente
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="space-y-4">
                                                <div className="flex items-center gap-2 bg-surface-2 p-2 rounded justify-between">
                                                    <div className="flex items-center gap-2">
                                                        <div className="w-2.5 h-2.5 rounded-full bg-[#d97757] animate-pulse shadow-[0_0_8px_rgba(217,119,87,0.6)]"></div>
                                                        <p className="text-xs font-semibold text-[#d97757] uppercase tracking-wider">Esperando Autorización en el Navegador...</p>
                                                    </div>
                                                </div>
                                                <div className="text-xs text-text-secondary">
                                                    <p className="mb-2">Por favor, revisa la ventana de tu navegador que acabamos de abrir.</p>
                                                    <p>Una vez completes el inicio de sesión exitosamente allí, cierra esta advertencia y haz clic en **Guardar Configuración**.</p>
                                                </div>
                                                <Button onClick={() => setDeviceLoginState(null)} size="sm" variant="ghost" className="w-full mt-4 text-xs text-text-secondary hover:text-text-primary border border-transparent hover:border-border-primary transition-all">
                                                    Entendido, volver
                                                </Button>
                                            </div>
                                        )}
                                        <input type="hidden" value={account} />
                                    </div>
                                ) : authMode === 'account' ? (
                                    <Input id="accountInput" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Session token o identificador..." className="bg-surface-0 border-border-primary text-text-primary w-full p-2.5 rounded-lg shadow-sm" />
                                ) : (
                                    <Input id="apiKeyInput" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." className="bg-surface-0 border-border-primary text-text-primary w-full p-2.5 rounded-lg shadow-sm" />
                                )}
                                {authMode === 'api_key' && <div className="text-[11px] text-text-secondary px-1">La clave se enviará de forma segura al orquestador.</div>}
                            </div>

                            {/* Model Selection */}
                            <div className="space-y-2">
                                <label htmlFor="modelIdSelect" className="block text-sm font-medium text-text-primary">Modelo</label>
                                <select
                                    id="modelIdSelect"
                                    value={modelId}
                                    onChange={(e) => setModelId(e.target.value)}
                                    className="w-full bg-surface-0 border border-border-primary rounded-lg p-2.5 text-sm text-text-primary focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all shadow-sm"
                                >
                                    <option value="">{isLoadingCatalog ? 'Cargando catálogo...' : 'Selecciona modelo'}</option>
                                    {modelGroups.installed.length > 0 && (
                                        <optgroup label="Instalados">
                                            {modelGroups.installed.map((m) => <option key={`i-${m.id}`} value={m.id}>{m.label}</option>)}
                                        </optgroup>
                                    )}
                                    {modelGroups.available.length > 0 && (
                                        <optgroup label="Disponibles para descargar">
                                            {modelGroups.available.map((m) => <option key={`a-${m.id}`} value={m.id}>{m.label}</option>)}
                                        </optgroup>
                                    )}
                                    {modelGroups.recommended.length > 0 && (
                                        <optgroup label="Recomendados">
                                            {modelGroups.recommended.map((m) => <option key={`r-${m.id}`} value={m.id}>{m.label}</option>)}
                                        </optgroup>
                                    )}
                                </select>
                            </div>

                            {/* Advanced Options Accordion */}
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
                                        </div>
                                        <div>
                                            <label htmlFor="orgInput" className="block text-xs text-text-secondary mb-1">Organization ID</label>
                                            <Input id="orgInput" value={org} onChange={(e) => setOrg(e.target.value)} className="bg-surface-1 border-border-primary text-text-primary text-sm rounded" />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Actions */}
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
                </div>

                {catalog?.warnings?.length ? (
                    <div className="mt-3 text-xs text-accent-warning space-y-1">
                        {catalog.warnings.map((w, idx) => <div key={`${w}-${idx}`}>⚠ {w}</div>)}
                    </div>
                ) : null}

                {accountModeAvailable || !accountModeRelevantProvider ? null : (
                    <div className="mt-3 text-xs text-accent-warning">Modo cuenta no disponible en este entorno; usa API key.</div>
                )}

                {!selectedModelInstalados && supportsInstall && modelId ? (
                    <div className="mt-4 p-3 rounded border border-border-primary bg-surface-0 flex items-center justify-between gap-3">
                        <div className="text-xs text-text-primary">Modelo no instalado. ¿Quieres descargarlo ahora?</div>
                        <Button onClick={() => void handleInstallAndUse()} className="bg-accent-primary hover:bg-accent-primary/80 text-white text-xs px-3 py-2">
                            <Download className="w-3.5 h-3.5 mr-1" />
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
            </Card>

            {/* Node Status */}
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

            <div className="space-y-3">
                <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">Providers Activos</h3>
                {providers.length === 0 && (
                    <div className="text-text-secondary text-center py-6 bg-surface-0/60 rounded border border-dashed border-border-primary">
                        Sin providers configurados. Gred funcionará en modo local limitado.
                    </div>
                )}
                {providers.map((p) => (
                    <Card key={p.id} className="bg-surface-2 border-border-primary p-4 flex items-center justify-between group hover:border-surface-3 transition-colors">
                        <div className="flex items-center gap-3">
                            <div className={`p-2 rounded-lg ${p.is_local ? 'bg-emerald-500/10 text-emerald-400' : 'bg-blue-500/10 text-blue-400'}`}>
                                {p.is_local ? <Cpu className="w-5 h-5" /> : <Cloud className="w-5 h-5" />}
                            </div>
                            <div>
                                <div className="font-medium text-text-primary">{p.config?.display_name || PROVIDER_LABELS[p.type] || p.id}</div>
                                <div className="text-xs text-text-secondary uppercase">{PROVIDER_LABELS[p.type] || p.type} • {p.is_local ? 'Local' : 'Cloud'}</div>
                                {p.capabilities && (
                                    <div className="text-[10px] text-text-secondary mt-1">
                                        auth: {(p.capabilities.auth_modes_supported || []).join(', ') || 'n/a'}
                                    </div>
                                )}
                                <div className="text-[10px] text-text-secondary">model: {p.model || p.config?.model || 'n/a'}</div>
                            </div>
                        </div>

                        <div className="flex items-center gap-2">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                    const result = await testProvider(p.id);
                                    addToast(result.message, result.healthy ? 'success' : 'error');
                                }}
                                className="text-text-secondary hover:text-text-primary"
                            >
                                <Activity className="w-4 h-4 mr-1" />
                                Probar
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                    try {
                                        await removeProvider(p.id);
                                        addToast(`Provider ${p.config?.display_name || p.id} eliminado`, 'info');
                                    } catch (err: any) {
                                        addToast(err?.message || 'No se pudo eliminar el provider', 'error');
                                    }
                                }}
                                className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                            >
                                <Trash2 className="w-4 h-4" />
                            </Button>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
};
