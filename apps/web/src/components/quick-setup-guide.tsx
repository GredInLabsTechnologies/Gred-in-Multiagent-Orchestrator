"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";

interface QuickSetupGuideProps {
    licenseKey?: string;  // si está disponible (show-once)
    keyPreview: string;
}

export function QuickSetupGuide({ licenseKey, keyPreview }: QuickSetupGuideProps) {
    const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

    const key = licenseKey ?? "<tu-clave-aqui>";
    const isWindows = typeof navigator !== "undefined" && navigator.userAgent.includes("Win");

    const commands = [
        {
            label: "Windows (CMD)",
            code: `set ORCH_LICENSE_KEY=${key}`,
        },
        {
            label: "Linux / macOS",
            code: `export ORCH_LICENSE_KEY=${key}`,
        },
        {
            label: ".env / config",
            code: `ORCH_LICENSE_KEY=${key}`,
        },
    ];

    async function handleCopy(idx: number, code: string) {
        await navigator.clipboard.writeText(code);
        setCopiedIdx(idx);
        setTimeout(() => setCopiedIdx(null), 2000);
    }

    return (
        <div className="rounded-xl border border-border bg-card p-6 space-y-4">
            <span className="text-lg font-semibold">⚡ Configuración rápida</span>
            <p className="text-sm text-muted-foreground">
                Copia el comando correspondiente a tu sistema para configurar GIMO Server:
            </p>
            <div className="space-y-2">
                {commands.map((cmd, i) => (
                    <div key={i} className="space-y-1">
                        <p className="text-xs text-muted-foreground">{cmd.label}</p>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 bg-muted px-3 py-2 rounded-lg text-xs font-mono truncate">
                                {licenseKey ? cmd.code : cmd.code.replace(key, `...${keyPreview}`)}
                            </code>
                            <button
                                onClick={() => handleCopy(i, cmd.code)}
                                disabled={!licenseKey}
                                className="p-2 rounded-lg hover:bg-muted transition-colors disabled:opacity-40"
                                title={licenseKey ? "Copiar" : "Necesitas ver la clave primero"}
                            >
                                {copiedIdx === i ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                            </button>
                        </div>
                    </div>
                ))}
            </div>
            <p className="text-xs text-muted-foreground">
                Después arranca GIMO Server normalmente. Buscará la variable de entorno automáticamente.
            </p>
        </div>
    );
}
