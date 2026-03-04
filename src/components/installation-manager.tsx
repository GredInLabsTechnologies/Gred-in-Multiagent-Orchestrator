"use client";

import { useState } from "react";
import { Monitor, Trash2 } from "lucide-react";

interface Activation {
    id: string;
    machineLabel: string;
    os: string;
    hostname: string;
    activatedAt?: string;
    lastHeartbeat?: string;
}

interface InstallationManagerProps {
    activations: Activation[];
    maxInstallations: number;
    onDeactivate: (activationId: string) => Promise<void>;
}

export function InstallationManager({ activations, maxInstallations, onDeactivate }: InstallationManagerProps) {
    const [deactivating, setDeactivating] = useState<string | null>(null);

    async function handleDeactivate(id: string) {
        setDeactivating(id);
        try {
            await onDeactivate(id);
        } finally {
            setDeactivating(null);
        }
    }

    const emptySlots = Math.max(0, maxInstallations - activations.length);

    return (
        <div className="rounded-xl border border-border bg-card p-6 space-y-4">
            <div className="flex items-center justify-between">
                <span className="text-lg font-semibold">💻 Instalaciones</span>
                <span className="text-sm text-muted-foreground">
                    {activations.length} / {maxInstallations} usadas
                </span>
            </div>

            <div className="space-y-2">
                {activations.map((a) => (
                    <div key={a.id} className="flex items-center gap-3 p-3 rounded-lg bg-muted">
                        <Monitor size={16} className="shrink-0 text-green-500" />
                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{a.machineLabel || a.hostname}</p>
                            <p className="text-xs text-muted-foreground">
                                {a.os} • Activa •{" "}
                                {a.lastHeartbeat
                                    ? `Última verificación: ${new Date(a.lastHeartbeat).toLocaleDateString()}`
                                    : `Activada: ${a.activatedAt ? new Date(a.activatedAt).toLocaleDateString() : "—"}`}
                            </p>
                        </div>
                        <button
                            onClick={() => handleDeactivate(a.id)}
                            disabled={deactivating === a.id}
                            className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors disabled:opacity-50"
                            title="Desactivar instalación"
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                ))}

                {Array.from({ length: emptySlots }).map((_, i) => (
                    <div key={`empty-${i}`} className="flex items-center gap-3 p-3 rounded-lg border border-dashed border-border">
                        <Monitor size={16} className="shrink-0 text-muted-foreground/40" />
                        <p className="text-sm text-muted-foreground/60">Slot disponible</p>
                    </div>
                ))}
            </div>
        </div>
    );
}
