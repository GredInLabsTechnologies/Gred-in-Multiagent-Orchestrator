import React, { useMemo, useState, useEffect } from 'react';
import { Card } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { useProviders } from '../hooks/useProviders';
import { useToast } from './Toast';
import { Server, Cloud, Cpu, Trash2, Activity, Download, CheckCircle2, AlertTriangle } from 'lucide-react';

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

    // Codex device flow state
    const [deviceLoginState, setDeviceLoginState] = useState<{ status: string; verification_url?: string; user_code?: string; message?: string } | null>(null);

    const providerTypes = Object.keys(providerCapabilities);
    const catalog = catalogs[providerType];
    const isLoadingCatalog = Boolean(catalogLoading[providerType]);
    const authModes = catalog?.auth_modes_supported || providerCapabilities[providerType]?.auth_modes_supported || [];
    const supportsInstall = Boolean(catalog?.can_install);
    const accountModeAvailable = authModes.includes('account');
    const accountModeRelevantProvider = providerType === 'openai' || providerType === 'codex';
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

    const handleInstallAndUse = async () => {
        if (!modelId) {
            addToast('Selecciona un modelo para instalar', 'error');
            return;
        }
        try {
            const res = await installModel(providerType, modelId);
            setInstallState(res);
            addToast(res?.message || 'Instalación lanzada', 'info');
        } catch {
            addToast('Error instalando el modelo', 'error');
        }
    };

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

    const handleStartDeviceLogin = async () => {
        try {
            setDeviceLoginState({ status: 'starting', message: 'Iniciando conexión interactiva...' });
            const data = await startCodexDeviceLogin();
            setDeviceLoginState(data);
            if (data.status === 'pending') {
                // If it's real, the user finishes in browser, codex CLI saves token globally, 
                // and the user can just click "Save" after. 
                // In our implementation, we auto-fill a dummy account ref if empty 
                // to satisfy the requirement of saving an account mode provider.
                if (!account) {
                    setAccount('codex-device-session');
                }
            }
        } catch (err: any) {
            setDeviceLoginState({ status: 'error', message: err.message || 'Error al iniciar flujo' });
            addToast('Error al conectar cuenta Codex', 'error');
        }
    };

    const handleSaveAsActive = async () => {
        if (!providerId.trim() || !modelId.trim()) {
            addToast('Provider ID y modelo son obligatorios', 'error');
            return;
        }
        try {
            await saveActiveProvider({
                providerId: providerId.trim(),
                providerType: providerType,
                modelId: modelId.trim(),
                authMode,
                apiKey: authMode === 'api_key' ? apiKey : undefined,
                account: authMode === 'account' ? account : undefined,
                baseUrl: baseUrl || undefined,
                org: org || undefined,
            });
            addToast('Provider activo guardado', 'success');

            // Clean up UI states after successful save, specially for Device Login flows
            if (authMode === 'account' && providerType === 'codex') {
                setDeviceLoginState(null);
            }
        } catch {
            addToast('No se pudo guardar provider activo', 'error');
        }
    };

    return (
        <div className="space-y-6 text-[#f5f5f7] p-4">
            <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold flex items-center gap-2">
                    <Server className="w-5 h-5 text-indigo-400" />
                    Configuración de Providers
                </h2>
            </div>

            <Card className="bg-[#1c1c1e] border-[#2c2c2e] p-4">
                <h3 className="text-sm font-semibold mb-3 text-[#86868b] uppercase tracking-wider">Estado efectivo actual</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                    <div><span className="text-[#86868b]">Provider activo:</span> <span className="font-semibold">{effectiveState?.active || 'n/a'}</span></div>
                    <div><span className="text-[#86868b]">Modelo efectivo:</span> <span className="font-semibold">{effectiveState?.model_id || 'n/a'}</span></div>
                    <div><span className="text-[#86868b]">Role:</span> <span className="font-semibold">{roleLabel}</span></div>
                    <div><span className="text-[#86868b]">Health:</span> <span className="font-semibold">{effectiveHealth}</span></div>
                    <div className="md:col-span-2"><span className="text-[#86868b]">Error accionable:</span> <span className="font-semibold text-[#ff9f0a]">{effectiveActionableError}</span></div>
                </div>
            </Card>

            <Card className="bg-[#1c1c1e] border-[#2c2c2e] p-4">
                <h3 className="text-sm font-semibold mb-3 text-[#86868b] uppercase tracking-wider">Configurar provider</h3>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
                    <div>
                        <label className="block text-xs text-[#86868b] mb-1">Provider Type</label>
                        <select
                            value={providerType}
                            onChange={(e) => {
                                setProviderType(e.target.value);
                                setProviderId(`${e.target.value}-main`);
                                setModelId('');
                                setValidateResult(null);
                            }}
                            className="w-full bg-[#0a0a0a] border border-[#2c2c2e] rounded p-2 text-sm text-[#f5f5f7]"
                        >
                            {(providerTypes.length > 0 ? providerTypes : ['openai', 'codex', 'ollama_local', 'groq', 'openrouter', 'custom_openai_compatible']).map((canonical) => (
                                <option key={canonical} value={canonical}>{canonical}</option>
                            ))}
                        </select>
                    </div>
                    {providerType === 'ollama_local' ? (
                        <div className="col-span-full mt-4 space-y-4">
                            {!catalog ? (
                                <div className="p-8 text-center bg-[#0a0a0a] rounded border border-[#2c2c2e] text-[#86868b]">
                                    {isLoadingCatalog ? 'Buscando servidor Ollama local...' : 'No se pudo conectar con Ollama.'}
                                </div>
                            ) : (
                                <>
                                    <div className="flex items-center justify-between mb-2">
                                        <div>
                                            <h4 className="text-sm font-semibold text-white">Modelos Detectados (Zero-Config)</h4>
                                            <p className="text-xs text-[#86868b]">No necesitas API Keys. Selecciona un modelo para asignar su rol en el enjambre.</p>
                                        </div>
                                    </div>
                                    {modelGroups.installed.length === 0 ? (
                                        <div className="p-8 text-center bg-[#0a0a0a] rounded border border-[#2c2c2e] text-[#86868b]">
                                            Ollama está instalado, pero no tienes modelos descargados.
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                                            {modelGroups.installed.map(m => (
                                                <div key={m.id} className="p-3 bg-[#0a0a0a] border border-[#2c2c2e] hover:border-[#3a3a3c] rounded-xl flex flex-col justify-between transition-colors">
                                                    <div>
                                                        <div className="font-semibold text-sm text-white truncate" title={m.label}>{m.label}</div>
                                                        <div className="text-[10px] text-[#86868b] uppercase tracking-wider">{m.size || 'Desconocido'}</div>
                                                    </div>
                                                    <div className="flex items-center gap-2 mt-4">
                                                        <Button
                                                            size="sm"
                                                            className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] h-7 px-2"
                                                            onClick={() => {
                                                                setProviderId('ollama-main');
                                                                setModelId(m.id);
                                                                setAuthMode('none');
                                                                // Esperar un tick para que react actualice el estado antes de guardar
                                                                setTimeout(() => handleSaveAsActive(), 50);
                                                            }}
                                                        >
                                                            Asignar Orchestrator
                                                        </Button>
                                                        <Button
                                                            size="sm"
                                                            className="flex-1 bg-[#2c2c2e] hover:bg-[#3a3a3c] text-white text-[11px] h-7 px-2"
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

                                    <div className="mt-6 border-t border-[#2c2c2e] pt-4">
                                        <h4 className="text-sm font-semibold text-white mb-2">Descargar Modelos (Pull)</h4>
                                        <p className="text-xs text-[#86868b] mb-4">Descarga nuevos modelos directamente desde el registro de Ollama.</p>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            {modelGroups.recommended.filter((m: any) => !m.installed).map((m: any) => (
                                                <div key={m.id} className="p-3 bg-[#1c1c1e] border border-[#2c2c2e] hover:border-[#3a3a3c] transition-colors rounded-xl flex items-center justify-between">
                                                    <div>
                                                        <div className="text-sm text-white font-medium">{m.label || m.id}</div>
                                                        <div className="text-xs text-[#86868b]">{m.id}</div>
                                                    </div>
                                                    <Button
                                                        size="sm"
                                                        className="bg-[#2c2c2e] hover:bg-[#0a84ff] hover:text-white transition-colors text-xs"
                                                        onClick={() => {
                                                            setModelId(m.id);
                                                            // Esperar que React refresque el estado de modelId antes de saltar la instalación
                                                            setTimeout(() => {
                                                                const installBtn = document.getElementById('hidden-install-btn');
                                                                if (installBtn) installBtn.click();
                                                            }, 100);
                                                        }}
                                                    >
                                                        <Download className="w-3.5 h-3.5 mr-1" />
                                                        Pull
                                                    </Button>
                                                </div>
                                            ))}

                                            <div className="p-3 bg-[#1c1c1e] border border-[#2c2c2e] rounded-xl flex flex-col justify-between">
                                                <div className="text-sm text-white font-medium mb-2">Otro Modelo...</div>
                                                <div className="flex items-center gap-2">
                                                    <Input
                                                        placeholder="ej: mistral:instruct"
                                                        className="h-8 text-xs bg-[#0a0a0a] border-[#2c2c2e] text-white"
                                                        value={modelId}
                                                        onChange={(e) => setModelId(e.target.value)}
                                                    />
                                                    <Button
                                                        id="hidden-install-btn"
                                                        size="sm"
                                                        title="Pull desde Ollama"
                                                        className="bg-[#2c2c2e] hover:bg-[#0a84ff] hover:text-white transition-colors text-xs shrink-0 h-8 w-8 p-0 flex items-center justify-center hidden-button-visible"
                                                        onClick={() => {
                                                            if (modelId) handleInstallAndUse();
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
                        <>
                            <div>
                                <label htmlFor="providerIdInput" className="block text-xs text-[#86868b] mb-1">ID (Name)</label>
                                <Input id="providerIdInput" value={providerId} onChange={(e) => setProviderId(e.target.value)} className="bg-[#0a0a0a] border-[#2c2c2e] text-[#f5f5f7]" />
                            </div>

                            <div>
                                <label htmlFor="modelIdSelect" className="block text-xs text-[#86868b] mb-1">ID/Name (modelo)</label>
                                <select
                                    id="modelIdSelect"
                                    value={modelId}
                                    onChange={(e) => setModelId(e.target.value)}
                                    className="w-full bg-[#0a0a0a] border border-[#2c2c2e] rounded p-2 text-sm text-[#f5f5f7]"
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

                            <div>
                                <label htmlFor="authModeSelect" className="block text-xs text-[#86868b] mb-1">Modo auth</label>
                                <select
                                    id="authModeSelect"
                                    value={authMode}
                                    onChange={(e) => setAuthMode(e.target.value)}
                                    className="w-full bg-[#0a0a0a] border border-[#2c2c2e] rounded p-2 text-sm text-[#f5f5f7]"
                                >
                                    {authModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
                                    {authModes.length === 0 && <option value="none">none</option>}
                                </select>
                            </div>

                            <div>
                                <label htmlFor="baseUrlInput" className="block text-xs text-[#86868b] mb-1">Base URL (opcional)</label>
                                <Input id="baseUrlInput" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://.../v1" className="bg-[#0a0a0a] border-[#2c2c2e] text-[#f5f5f7]" />
                            </div>

                            <div>
                                <label htmlFor="orgInput" className="block text-xs text-[#86868b] mb-1">Organization (opcional)</label>
                                <Input id="orgInput" value={org} onChange={(e) => setOrg(e.target.value)} className="bg-[#0a0a0a] border-[#2c2c2e] text-[#f5f5f7]" />
                            </div>

                            {authMode === 'api_key' && (
                                <div>
                                    <label htmlFor="apiKeyInput" className="block text-xs text-[#86868b] mb-1">API Key</label>
                                    <Input id="apiKeyInput" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." className="bg-[#0a0a0a] border-[#2c2c2e] text-[#f5f5f7]" />
                                </div>
                            )}
                            {authMode === 'account' && providerType !== 'codex' && (
                                <div>
                                    <label htmlFor="accountInput" className="block text-xs text-[#86868b] mb-1">Account</label>
                                    <Input id="accountInput" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="account/session token" className="bg-[#0a0a0a] border-[#2c2c2e] text-[#f5f5f7]" />
                                </div>
                            )}
                            {authMode === 'account' && providerType === 'codex' && (
                                <div className="col-span-full md:col-span-1 p-3 border border-[#2c2c2e] rounded bg-[#1c1c1e]">
                                    <label className="block text-sm font-semibold mb-2">Conectar Cuenta (Device Auth)</label>
                                    {!deviceLoginState || deviceLoginState.status === 'error' ? (
                                        <div>
                                            <p className="text-xs text-[#86868b] mb-3">
                                                Inicia sesión con tu cuenta de OpenAI (ChatGPT Plus/Pro) en lugar de usar una API Key.
                                            </p>
                                            <Button onClick={handleStartDeviceLogin} className="w-full bg-[#0a84ff] hover:bg-[#409cff] text-white">
                                                Conectar Cuenta
                                            </Button>
                                            {deviceLoginState?.status === 'error' && (
                                                <div className="mt-2 text-xs text-[#ff3b30]">{deviceLoginState.message}</div>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="space-y-2">
                                            <p className="text-xs text-[#86868b]">Estado: <span className="text-[#32d74b] uppercase">{deviceLoginState.status}</span></p>
                                            {deviceLoginState.verification_url && (
                                                <p className="text-xs">
                                                    1. Abre <a href={deviceLoginState.verification_url} target="_blank" rel="noreferrer" className="text-[#0a84ff] hover:underline">{deviceLoginState.verification_url}</a>
                                                </p>
                                            )}
                                            {deviceLoginState.user_code && (
                                                <p className="text-xs">
                                                    2. Introduce el código: <span className="font-mono bg-[#0a0a0a] p-1 rounded font-bold">{deviceLoginState.user_code}</span>
                                                </p>
                                            )}
                                            <p className="text-xs text-[#ff9f0a] italic">{deviceLoginState.message}</p>
                                            <Button onClick={() => setDeviceLoginState(null)} size="sm" variant="outline" className="w-full mt-2 text-xs border-[#2c2c2e] text-[#f5f5f7] hover:bg-[#2c2c2e]">
                                                Cancelar / Reintentar
                                            </Button>
                                        </div>
                                    )}
                                    <input type="hidden" value={account} />
                                </div>
                            )}

                            <Button onClick={handleTestConnection} className="bg-[#2c2c2e] hover:bg-[#3a3a3c] text-white">
                                Probar conexión
                            </Button>
                            <Button onClick={handleSaveAsActive} className="bg-indigo-600 hover:bg-indigo-500 text-white">
                                Guardar como provider activo
                            </Button>
                        </>
                    )}
                </div>

                {catalog?.warnings?.length ? (
                    <div className="mt-3 text-xs text-[#ff9f0a] space-y-1">
                        {catalog.warnings.map((w, idx) => <div key={`${w}-${idx}`}>⚠ {w}</div>)}
                    </div>
                ) : null}

                {accountModeAvailable || !accountModeRelevantProvider ? null : (
                    <div className="mt-3 text-xs text-[#ff9f0a]">Modo cuenta no disponible en este entorno; usa API key.</div>
                )}

                {!selectedModelInstalados && supportsInstall && modelId ? (
                    <div className="mt-4 p-3 rounded border border-[#2c2c2e] bg-[#0a0a0a] flex items-center justify-between gap-3">
                        <div className="text-xs text-[#f5f5f7]">Modelo no instalado. ¿Quieres descargarlo ahora?</div>
                        <Button onClick={handleInstallAndUse} className="bg-[#0a84ff] hover:bg-[#409cff] text-white text-xs px-3 py-2">
                            <Download className="w-3.5 h-3.5 mr-1" />
                            Descargar y usar
                        </Button>
                    </div>
                ) : null}

                {installState ? (
                    <div className="mt-3 p-3 rounded border border-[#2c2c2e] bg-[#0a0a0a]">
                        <div className="text-xs text-[#f5f5f7]">Instalación: {installState.status}</div>
                        <div className="text-xs text-[#86868b]">{installState.message}</div>
                        {typeof installState.progress === 'number' ? (
                            <div className="text-xs text-[#86868b]">Progreso: {Math.round(installState.progress * 100)}%</div>
                        ) : null}
                    </div>
                ) : null}

                {validateResult ? (
                    <div className={`mt-4 p-3 rounded border ${validateResult.valid ? 'border-[#32d74b]/40 bg-[#32d74b]/10' : 'border-[#ff3b30]/40 bg-[#ff3b30]/10'}`}>
                        <div className="flex items-center gap-2 text-sm">
                            {validateResult.valid ? <CheckCircle2 className="w-4 h-4 text-[#32d74b]" /> : <AlertTriangle className="w-4 h-4 text-[#ff3b30]" />}
                            <span>{validateResult.valid ? 'Conexión válida' : 'Conexión no válida'}</span>
                            <span className="text-xs text-[#86868b]">health: {validateResult.health}</span>
                        </div>
                        {validateResult.error_actionable ? <div className="mt-2 text-xs">Acción sugerida: {validateResult.error_actionable}</div> : null}
                    </div>
                ) : null}
            </Card>

            {/* Node Status */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.entries(nodes).map(([id, node]: [string, any]) => (
                    <Card key={id} className="bg-[#1c1c1e]/70 border-[#2c2c2e] p-3">
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-semibold text-sm flex items-center gap-2">
                                {id === 'ally_x' ? <Cpu className="w-4 h-4 text-emerald-400" /> : <Server className="w-4 h-4 text-blue-400" />}
                                {node.name}
                            </span>
                            <span className="text-xs text-[#86868b]">{node.type}</span>
                        </div>
                        <div className="w-full bg-[#0a0a0a] h-2 rounded-full overflow-hidden">
                            <div
                                className={`h-full transition-all duration-500 ${node.current_load >= node.max_concurrency ? 'bg-red-500' : 'bg-emerald-500'}`}
                                style={{ width: `${(node.current_load / node.max_concurrency) * 100}%` }}
                            />
                        </div>
                        <div className="flex justify-between mt-1 text-xs text-[#86868b]">
                            <span>Load: {node.current_load} / {node.max_concurrency} agents</span>
                            <span>{node.current_load >= node.max_concurrency ? 'FULL' : 'AVAILABLE'}</span>
                        </div>
                    </Card>
                ))}
            </div>

            <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[#86868b] uppercase tracking-wider">Providers Activos</h3>
                {providers.length === 0 && (
                    <div className="text-[#86868b] text-center py-6 bg-[#0a0a0a]/60 rounded border border-dashed border-[#2c2c2e]">
                        Sin providers configurados. Gred funcionará en modo local limitado.
                    </div>
                )}
                {providers.map((p) => (
                    <Card key={p.id} className="bg-[#1c1c1e] border-[#2c2c2e] p-4 flex items-center justify-between group hover:border-[#3a3a3c] transition-colors">
                        <div className="flex items-center gap-3">
                            <div className={`p-2 rounded-lg ${p.is_local ? 'bg-emerald-500/10 text-emerald-400' : 'bg-blue-500/10 text-blue-400'}`}>
                                {p.is_local ? <Cpu className="w-5 h-5" /> : <Cloud className="w-5 h-5" />}
                            </div>
                            <div>
                                <div className="font-medium text-[#f5f5f7]">{p.id}</div>
                                <div className="text-xs text-[#86868b] uppercase">{p.type} • {p.is_local ? 'Local' : 'Cloud'}</div>
                                {p.capabilities && (
                                    <div className="text-[10px] text-[#6e6e73] mt-1">
                                        auth: {(p.capabilities.auth_modes_supported || []).join(', ') || 'n/a'}
                                    </div>
                                )}
                                <div className="text-[10px] text-[#6e6e73]">model: {p.model || p.config?.model || 'n/a'}</div>
                            </div>
                        </div>

                        <div className="flex items-center gap-2">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => testProvider(p.id)}
                                className="text-[#86868b] hover:text-[#f5f5f7]"
                            >
                                <Activity className="w-4 h-4 mr-1" />
                                Test
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => removeProvider(p.id)}
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
