import React from 'react';
import { Button } from '../ui/button';
import { Download } from 'lucide-react';

interface CodexAuthSectionProps {
    cliAuthStatus: { authenticated: boolean; method?: string | null; email?: string | null; detail?: string } | null;
    cliAuthLoading: boolean;
    deviceLoginState: { status: string; verification_url?: string; user_code?: string; message?: string; action?: string } | null;
    installState: { status: string; message: string; progress?: number; job_id?: string; is_cli?: boolean; dependency_id?: string } | null;
    account: string;
    onLogin: () => void;
    onLogout: () => void;
    onInstallCli: (dependencyId: string) => void;
    onCancelDeviceLogin: () => void;
    onCopyCode: () => void;
    addToast: (msg: string, type?: 'error' | 'success' | 'info') => void;
}

export const CodexAuthSection: React.FC<CodexAuthSectionProps> = ({
    cliAuthStatus,
    cliAuthLoading,
    deviceLoginState,
    installState,
    account,
    onLogin,
    onLogout,
    onInstallCli,
    onCancelDeviceLogin,
    onCopyCode,
}) => {
    return (
        <div className="p-4 border border-border-primary rounded-lg bg-surface-1">
            {cliAuthLoading ? (
                <div className="text-xs text-text-secondary animate-pulse">Comprobando sesión...</div>
            ) : cliAuthStatus?.authenticated ? (
                <div className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-[#10a37f] shadow-[0_0_8px_rgba(16,163,127,0.6)]" />
                        <span className="text-sm font-semibold text-[#10a37f]">Conectado con OpenAI Codex</span>
                    </div>
                    <div className="text-xs text-text-secondary space-y-1">
                        {cliAuthStatus.method && <div>Método: <span className="text-text-primary">{cliAuthStatus.method}</span></div>}
                        {cliAuthStatus.email && <div>Cuenta: <span className="text-text-primary">{cliAuthStatus.email}</span></div>}
                    </div>
                    <button
                        type="button"
                        onClick={onLogout}
                        className="text-xs text-accent-alert hover:underline self-start"
                    >
                        Cerrar sesión
                    </button>
                </div>
            ) : (!deviceLoginState || deviceLoginState.status === 'error') ? (
                <div className="flex flex-col gap-3">
                    <div>
                        <div className="text-sm font-medium">Cuenta OpenAI – Codex CLI</div>
                        <div className="text-xs text-text-secondary mt-1">Usa los modelos Codex a los que ya tienes acceso (Plus/Pro) sin pagar por token vía API Key.</div>
                        {deviceLoginState?.status === 'error' && (
                            <div className="mt-2 text-xs text-accent-alert bg-accent-alert/10 p-2 rounded space-y-2">
                                <div>{deviceLoginState.message}</div>
                                {deviceLoginState.action ? (
                                    <button
                                        type="button"
                                        onClick={() => onInstallCli('codex_cli')}
                                        className="inline-flex items-center gap-1 px-2 py-1 rounded border border-accent-alert/40 hover:bg-accent-alert/20 text-[11px]"
                                        disabled={installState?.status === 'queued' || installState?.status === 'running'}
                                    >
                                        {(installState?.status === 'queued' || installState?.status === 'running') && installState.is_cli ? (
                                            <><Download className="w-3 h-3 animate-bounce" /> Instalando...</>
                                        ) : (
                                            <><Download className="w-3 h-3" /> Instalar Codex CLI automáticamente</>
                                        )}
                                    </button>
                                ) : null}
                            </div>
                        )}
                    </div>
                    <Button onClick={onLogin} className="w-full bg-[#10a37f] hover:bg-[#0e906f] text-white flex items-center justify-center gap-2 shadow-md h-10 transition-colors">
                        Autenticar con OpenAI (Codex)
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
                                                onClick={onCopyCode}
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
                    <Button onClick={onCancelDeviceLogin} size="sm" variant="ghost" className="w-full mt-4 text-xs text-text-secondary hover:text-text-primary border border-transparent hover:border-border-primary transition-all">
                        Cancelar y Reintentar
                    </Button>
                </div>
            )}
            <input type="hidden" value={account} />
        </div>
    );
};
