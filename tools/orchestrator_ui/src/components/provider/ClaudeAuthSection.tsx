import React from 'react';
import { Button } from '../ui/button';
import { Download } from 'lucide-react';

interface ClaudeAuthSectionProps {
    cliAuthStatus: { authenticated: boolean; method?: string | null; email?: string | null; plan?: string | null; detail?: string } | null;
    cliAuthLoading: boolean;
    deviceLoginState: { status: string; verification_url?: string; user_code?: string; message?: string; action?: string } | null;
    installState: { status: string; message: string; progress?: number; job_id?: string; is_cli?: boolean; dependency_id?: string } | null;
    account: string;
    onLogin: () => void;
    onLogout: () => void;
    onInstallCli: (dependencyId: string) => void;
    onCancelDeviceLogin: () => void;
}

export const ClaudeAuthSection: React.FC<ClaudeAuthSectionProps> = ({
    cliAuthStatus,
    cliAuthLoading,
    deviceLoginState,
    installState,
    account,
    onLogin,
    onLogout,
    onInstallCli,
    onCancelDeviceLogin,
}) => {
    return (
        <div className="p-4 border border-border-primary rounded-lg bg-surface-1">
            {cliAuthLoading ? (
                <div className="text-xs text-text-secondary animate-pulse">Comprobando sesión...</div>
            ) : cliAuthStatus?.authenticated ? (
                <div className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-[#d97757] shadow-[0_0_8px_rgba(217,119,87,0.6)]" />
                        <span className="text-sm font-semibold text-[#d97757]">Conectado con Anthropic</span>
                    </div>
                    <div className="text-xs text-text-secondary space-y-1">
                        {cliAuthStatus.email && <div>Cuenta: <span className="text-text-primary">{cliAuthStatus.email}</span></div>}
                        {cliAuthStatus.plan && <div>Plan: <span className="text-text-primary capitalize">{cliAuthStatus.plan}</span></div>}
                        {cliAuthStatus.method && <div>Método: <span className="text-text-primary">{cliAuthStatus.method}</span></div>}
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
                        <div className="text-sm font-medium">Cuenta de Anthropic (Pro/Team)</div>
                        <div className="text-xs text-text-secondary mt-1">Usa tu sesión local de Claude (requiere claude CLI instalada).</div>
                        {deviceLoginState?.status === 'error' && (
                            <div className="mt-2 text-xs text-accent-alert bg-accent-alert/10 p-2 rounded space-y-2">
                                <div>{deviceLoginState.message}</div>
                                {deviceLoginState.action ? (
                                    <button
                                        type="button"
                                        onClick={() => onInstallCli('claude_cli')}
                                        className="inline-flex items-center gap-1 px-2 py-1 rounded border border-accent-alert/40 hover:bg-accent-alert/20 text-[11px]"
                                        disabled={installState?.status === 'queued' || installState?.status === 'running'}
                                    >
                                        {(installState?.status === 'queued' || installState?.status === 'running') && installState.is_cli ? (
                                            <>
                                                <Download className="w-3 h-3 animate-bounce" /> Instalando...
                                            </>
                                        ) : (
                                            <>
                                                <Download className="w-3 h-3" /> Instalar Claude CLI automáticamente
                                            </>
                                        )}
                                    </button>
                                ) : null}
                            </div>
                        )}
                    </div>
                    <Button onClick={onLogin} className="w-full bg-[#d97757] hover:bg-[#b86246] text-white flex items-center justify-center gap-2 shadow-md h-10 transition-colors">
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
                    <Button onClick={onCancelDeviceLogin} size="sm" variant="ghost" className="w-full mt-4 text-xs text-text-secondary hover:text-text-primary border border-transparent hover:border-border-primary transition-all">
                        Entendido, volver
                    </Button>
                </div>
            )}
            <input type="hidden" value={account} />
        </div>
    );
};
