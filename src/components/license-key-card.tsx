"use client";

import { useState } from "react";
import { Copy, Check, RefreshCw, Eye, EyeOff } from "lucide-react";
import { RegenerateModal } from "./regenerate-modal";

interface LicenseKeyCardProps {
    rawKey?: string;        // presente solo si es show-once
    keyPreview: string;     // "...a1b2c3d4"
    onRegenerate: () => Promise<void>;
}

export function LicenseKeyCard({ rawKey, keyPreview, onRegenerate }: LicenseKeyCardProps) {
    const [copied, setCopied] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [revealed, setRevealed] = useState(!!rawKey);

    const displayKey = rawKey ?? `••••••••••••••••••••••••••••••••...${keyPreview}`;

    async function handleCopy() {
        const toCopy = rawKey ?? keyPreview;
        await navigator.clipboard.writeText(toCopy);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }

    return (
        <div className="rounded-xl border border-border bg-card p-6 space-y-4">
            <div className="flex items-center gap-2">
                <span className="text-lg font-semibold">🔑 Tu Clave de Licencia</span>
                {rawKey && (
                    <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded-full font-medium">
                        NUEVA — solo se muestra una vez
                    </span>
                )}
            </div>

            {rawKey && (
                <div className="rounded-lg bg-yellow-50 border border-yellow-200 p-3 text-sm text-yellow-800">
                    ⚠️ <strong>Esta clave solo se mostrará una vez.</strong> Cópiala y guárdala en un lugar
                    seguro. Si la pierdes, deberás regenerarla.
                </div>
            )}

            <div className="flex items-center gap-2">
                <code className="flex-1 bg-muted px-3 py-2 rounded-lg text-sm font-mono break-all">
                    {revealed ? (rawKey ?? displayKey) : displayKey}
                </code>
                {rawKey && (
                    <button
                        onClick={() => setRevealed((v) => !v)}
                        className="p-2 rounded-lg hover:bg-muted transition-colors"
                        title={revealed ? "Ocultar" : "Mostrar"}
                    >
                        {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                )}
                <button
                    onClick={handleCopy}
                    className="p-2 rounded-lg hover:bg-muted transition-colors"
                    title="Copiar clave"
                >
                    {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
                </button>
            </div>

            {!rawKey && (
                <button
                    onClick={() => setShowModal(true)}
                    className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                    <RefreshCw size={14} />
                    Regenerar clave
                </button>
            )}

            <RegenerateModal
                open={showModal}
                onClose={() => setShowModal(false)}
                onConfirm={async () => {
                    await onRegenerate();
                    setShowModal(false);
                }}
            />
        </div>
    );
}
