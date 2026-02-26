import React, { useMemo, useState } from 'react';

interface Props {
    expiresAt?: string;
    daysRemaining?: number;
    plan?: string;
    features?: string[];
    renewalsRemaining?: number;
    loading: boolean;
    onRenew: (licenseBlob: string) => Promise<void>;
}

export const ColdRoomRenewalPanel: React.FC<Props> = ({
    expiresAt,
    daysRemaining,
    plan,
    features,
    renewalsRemaining,
    loading,
    onRenew,
}) => {
    const [blob, setBlob] = useState('');
    const canSubmit = useMemo(() => blob.trim().length > 24, [blob]);
    const blobLength = blob.trim().length;

    return (
        <div className="space-y-3 animate-slide-in-up">
            <div className="rounded-xl border border-accent-approval/40 bg-surface-2 p-3 animate-glow-pulse">
                <div className="text-[10px] uppercase tracking-wider text-text-secondary mb-2">Estado actual</div>
                <div className="space-y-1 text-xs text-text-secondary">
                    <div><span className="text-text-tertiary">Plan:</span> <span className="text-text-primary">{plan || 'n/a'}</span></div>
                    <div><span className="text-text-tertiary">Expira:</span> <span className="text-text-primary">{expiresAt || 'n/a'}</span></div>
                    <div><span className="text-text-tertiary">Días restantes:</span> <span className="text-text-primary">{daysRemaining ?? 0}</span></div>
                    <div><span className="text-text-tertiary">Renovaciones:</span> <span className="text-text-primary">{renewalsRemaining ?? 'n/a'}</span></div>
                    <div><span className="text-text-tertiary">Features:</span> <span className="text-text-primary">{(features || []).join(', ') || 'n/a'}</span></div>
                </div>
            </div>

            <div className="rounded-xl border border-border-primary bg-surface-2/70 p-3 text-xs text-text-secondary">
                Inserta un nuevo blob firmado para extender la validez de esta instalación Cold Room.
            </div>

            <textarea
                value={blob}
                onChange={(e) => setBlob(e.target.value)}
                placeholder="Pega aquí el nuevo license blob firmado"
                rows={4}
                className="w-full px-4 py-3 rounded-xl bg-surface-2 border border-border-primary text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-border-focus font-mono text-xs"
            />

            <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-secondary">Longitud del blob</span>
                <span className={blobLength > 24 ? 'text-accent-trust' : 'text-accent-warning'}>{blobLength} chars</span>
            </div>

            <button
                onClick={() => void onRenew(blob.trim())}
                disabled={loading || !canSubmit}
                className="w-full py-3 rounded-xl bg-accent-approval hover:bg-accent-approval/85 disabled:opacity-50 text-surface-0 text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
            >
                {loading ? 'Renovando...' : 'Renovar licencia Cold Room'}
            </button>
        </div>
    );
};
