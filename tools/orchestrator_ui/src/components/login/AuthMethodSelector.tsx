import React from 'react';
import { KeyRound, ShieldCheck, Sparkles } from 'lucide-react';

export type AuthMethod = 'google' | 'token' | 'cold-activate' | 'cold-renew';

interface Props {
    canUseColdRoom: boolean;
    paired?: boolean;
    renewalNeeded: boolean;
    vmDetected?: boolean;
    coldRoomLoading?: boolean;
    onSelect: (method: AuthMethod) => void;
}

const cardBase = 'rounded-2xl border bg-surface-2/60 backdrop-blur-lg p-4 text-left transition-all duration-200 hover:translate-y-[-1px] hover:scale-[1.02] active:scale-[0.99]';

export const AuthMethodSelector: React.FC<Props> = ({ canUseColdRoom, paired = false, renewalNeeded, vmDetected = false, coldRoomLoading = false, onSelect }) => {
    const coldMethod: AuthMethod = renewalNeeded ? 'cold-renew' : 'cold-activate';
    const coldSubtitle = !paired
        ? 'Licencia offline firmada para entornos air-gapped'
        : renewalNeeded
            ? 'Renovación requerida para mantener validez offline'
            : 'Instalación emparejada y válida. Continúa sin pegar blob';

    return (
        <div className="space-y-3 animate-slide-in-up">
            <button
                className={`${cardBase} w-full border-accent-primary/50 hover:shadow-[0_0_20px_var(--glow-primary)] animate-slide-in-up [animation-delay:20ms]`}
                onClick={() => onSelect('google')}
            >
                <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
                    <Sparkles size={14} className="text-accent-primary" /> Google SSO
                </div>
                <div className="text-xs text-text-secondary">Inicio de sesión recomendado para operación diaria</div>
            </button>

            <button
                className={`${cardBase} w-full border-border-primary hover:border-accent-primary/40 animate-slide-in-up [animation-delay:80ms]`}
                onClick={() => onSelect('token')}
            >
                <div className="flex items-center gap-2 text-sm font-semibold text-text-primary"><KeyRound size={14} /> Token local</div>
                <div className="text-xs text-text-secondary">Acceso manual para desarrollo / fallback</div>
            </button>

            {coldRoomLoading && (
                <div className={`${cardBase} w-full border-border-primary/70 animate-pulse`} aria-hidden="true">
                    <div className="h-4 w-40 rounded bg-surface-3/80 mb-2" />
                    <div className="h-3 w-56 rounded bg-surface-3/60" />
                </div>
            )}

            {canUseColdRoom && !coldRoomLoading && (
                <button
                    className={`${cardBase} w-full border-accent-trust/50 hover:shadow-[0_0_20px_var(--glow-trust)] animate-slide-in-up [animation-delay:140ms]`}
                    onClick={() => onSelect(coldMethod)}
                >
                    <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
                        <ShieldCheck size={14} className="text-accent-trust" /> Sala Limpia
                        {renewalNeeded && <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-approval/20 text-accent-approval border border-accent-approval/40">Renovación</span>}
                        {!renewalNeeded && paired && <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-trust/20 text-accent-trust border border-accent-trust/40">Activa</span>}
                        {vmDetected && <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-warning/20 text-accent-warning border border-accent-warning/40">VM detectada</span>}
                    </div>
                    <div className="text-xs text-text-secondary">{coldSubtitle}</div>
                </button>
            )}
        </div>
    );
};
