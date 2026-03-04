"use client";

import { useState } from "react";

interface RegenerateModalProps {
    open: boolean;
    onClose: () => void;
    onConfirm: () => Promise<void>;
}

export function RegenerateModal({ open, onClose, onConfirm }: RegenerateModalProps) {
    const [loading, setLoading] = useState(false);

    if (!open) return null;

    async function handleConfirm() {
        setLoading(true);
        try {
            await onConfirm();
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="bg-card rounded-xl border border-border p-6 max-w-md w-full mx-4 space-y-4">
                <h2 className="text-lg font-semibold">⚠️ Regenerar clave de licencia</h2>
                <p className="text-sm text-muted-foreground">
                    Al regenerar tu clave:
                </p>
                <ul className="text-sm text-muted-foreground list-disc pl-5 space-y-1">
                    <li>La clave actual dejará de funcionar inmediatamente</li>
                    <li>Todas tus instalaciones activas serán desactivadas</li>
                    <li>Deberás configurar GIMO Server con la nueva clave</li>
                    <li>Solo puedes regenerar una vez cada 24 horas</li>
                </ul>
                <p className="text-sm font-medium">¿Estás seguro de que quieres continuar?</p>
                <div className="flex justify-end gap-3 pt-2">
                    <button
                        onClick={onClose}
                        disabled={loading}
                        className="px-4 py-2 text-sm rounded-lg border border-border hover:bg-muted transition-colors"
                    >
                        Cancelar
                    </button>
                    <button
                        onClick={handleConfirm}
                        disabled={loading}
                        className="px-4 py-2 text-sm rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-50"
                    >
                        {loading ? "Regenerando..." : "Sí, regenerar"}
                    </button>
                </div>
            </div>
        </div>
    );
}
