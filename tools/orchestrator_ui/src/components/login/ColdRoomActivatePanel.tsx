import React, { useMemo, useState } from 'react';

interface Props {
    machineId?: string;
    loading: boolean;
    onActivate: (licenseBlob: string) => Promise<void>;
}

export const ColdRoomActivatePanel: React.FC<Props> = ({ machineId, loading, onActivate }) => {
    const [blob, setBlob] = useState('');
    const canSubmit = useMemo(() => blob.trim().length > 24, [blob]);
    const blobLength = blob.trim().length;

    return (
        <div className="space-y-3 animate-slide-in-up">
            <div className="rounded-xl border border-accent-trust/40 bg-surface-2 p-3 animate-glow-pulse">
                <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="text-[10px] uppercase tracking-wider text-text-secondary">Machine ID</div>
                    <button
                        type="button"
                        onClick={() => machineId && void navigator.clipboard.writeText(machineId)}
                        className="text-[10px] px-2 py-0.5 rounded border border-border-primary text-text-secondary hover:text-text-primary"
                    >
                        Copiar
                    </button>
                </div>
                <div className="font-mono text-sm text-text-primary">{machineId || 'GIMO-XXXX-XXXX'}</div>
            </div>

            <div className="rounded-xl border border-border-primary bg-surface-2/70 p-3 text-xs text-text-secondary">
                Pega el blob firmado emitido para esta máquina. La verificación valida firma, versión y binding de equipo.
            </div>

            <textarea
                value={blob}
                onChange={(e) => setBlob(e.target.value)}
                placeholder="Pega aquí el license blob firmado (base64url)"
                rows={4}
                className="w-full px-4 py-3 rounded-xl bg-surface-2 border border-border-primary text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-border-focus font-mono text-xs"
            />

            <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-secondary">Longitud del blob</span>
                <span className={blobLength > 24 ? 'text-accent-trust' : 'text-accent-warning'}>{blobLength} chars</span>
            </div>

            <button
                onClick={() => void onActivate(blob.trim())}
                disabled={loading || !canSubmit}
                className="w-full py-3 rounded-xl bg-accent-trust hover:bg-accent-trust/85 disabled:opacity-50 text-white text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
            >
                {loading ? 'Activando licencia...' : 'Activar licencia Cold Room'}
            </button>
        </div>
    );
};
