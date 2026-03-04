"use client";

import { useState } from "react";

interface LicenseRow {
    id: string;
    email: string;
    plan: string;
    status: string;
    lifetime: boolean;
    activeInstallations: number;
    maxInstallations: number;
    keyPreview: string;
    createdAt?: string;
    expiresAt?: string | null;
}

interface AdminPanelProps {
    licenses: LicenseRow[];
    onCreateLifetime: (email: string, maxInstallations: number) => Promise<{ rawKey: string }>;
    onRevoke: (licenseId: string) => Promise<void>;
}

export function AdminPanel({ licenses, onCreateLifetime, onRevoke }: AdminPanelProps) {
    const [email, setEmail] = useState("");
    const [maxInstalls, setMaxInstalls] = useState(999);
    const [creating, setCreating] = useState(false);
    const [newKey, setNewKey] = useState<string | null>(null);
    const [revoking, setRevoking] = useState<string | null>(null);

    async function handleCreate() {
        if (!email) return;
        setCreating(true);
        setNewKey(null);
        try {
            const res = await onCreateLifetime(email, maxInstalls);
            setNewKey(res.rawKey);
            setEmail("");
        } finally {
            setCreating(false);
        }
    }

    async function handleRevoke(id: string) {
        if (!confirm("¿Revocar esta licencia? El servidor se detendrá en el próximo heartbeat.")) return;
        setRevoking(id);
        try {
            await onRevoke(id);
        } finally {
            setRevoking(null);
        }
    }

    const activeCount = licenses.filter((l) => l.status === "active").length;

    return (
        <div className="rounded-xl border border-destructive/30 bg-card p-6 space-y-6">
            <div className="flex items-center justify-between">
                <span className="text-lg font-semibold">🛡️ Panel Admin</span>
                <div className="flex gap-4 text-sm">
                    <span className="text-muted-foreground">Licencias activas: <strong>{activeCount}</strong></span>
                    <span className="text-muted-foreground">Revenue est: <strong>${activeCount * 3}/mes</strong></span>
                </div>
            </div>

            {/* Crear licencia vitalicia */}
            <div className="space-y-3">
                <p className="text-sm font-medium">Crear licencia vitalicia</p>
                <div className="flex gap-2">
                    <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="email@destino.com"
                        className="flex-1 px-3 py-2 text-sm rounded-lg border border-border bg-background"
                    />
                    <input
                        type="number"
                        value={maxInstalls}
                        onChange={(e) => setMaxInstalls(Number(e.target.value))}
                        className="w-20 px-3 py-2 text-sm rounded-lg border border-border bg-background"
                        title="Max instalaciones"
                    />
                    <button
                        onClick={handleCreate}
                        disabled={creating || !email}
                        className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                        {creating ? "Creando..." : "Crear"}
                    </button>
                </div>
                {newKey && (
                    <div className="p-3 rounded-lg bg-green-50 border border-green-200 text-sm">
                        <p className="font-medium text-green-800">✅ Licencia creada — clave (solo esta vez):</p>
                        <code className="text-green-900 break-all font-mono text-xs mt-1 block">{newKey}</code>
                    </div>
                )}
            </div>

            {/* Tabla de licencias */}
            <div className="space-y-2">
                <p className="text-sm font-medium">Licencias ({licenses.length})</p>
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="text-left text-muted-foreground border-b border-border">
                                <th className="pb-2 pr-3">Email</th>
                                <th className="pb-2 pr-3">Plan</th>
                                <th className="pb-2 pr-3">Estado</th>
                                <th className="pb-2 pr-3">Inst.</th>
                                <th className="pb-2">Acciones</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {licenses.map((lic) => (
                                <tr key={lic.id}>
                                    <td className="py-2 pr-3 truncate max-w-[150px]">{lic.email}</td>
                                    <td className="py-2 pr-3 capitalize">
                                        {lic.plan}{lic.lifetime ? " ∞" : ""}
                                    </td>
                                    <td className="py-2 pr-3">
                                        <span className={lic.status === "active" ? "text-green-600" : "text-muted-foreground"}>
                                            {lic.status === "active" ? "✅" : "❌"} {lic.status}
                                        </span>
                                    </td>
                                    <td className="py-2 pr-3">{lic.activeInstallations}/{lic.maxInstallations}</td>
                                    <td className="py-2">
                                        {lic.status !== "revoked" && (
                                            <button
                                                onClick={() => handleRevoke(lic.id)}
                                                disabled={revoking === lic.id}
                                                className="text-destructive hover:underline disabled:opacity-50"
                                            >
                                                Revocar
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
