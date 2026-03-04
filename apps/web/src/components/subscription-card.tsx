"use client";

interface SubscriptionCardProps {
    plan: string;
    status: string;
    currentPeriodEnd?: string;
    cancelAtPeriodEnd?: boolean;
    onManage: () => void;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
    active: { label: "Activa ✅", color: "text-green-600" },
    past_due: { label: "Pago fallido ⚠️", color: "text-yellow-600" },
    canceled: { label: "Cancelada", color: "text-muted-foreground" },
    incomplete: { label: "Incompleta", color: "text-muted-foreground" },
};

export function SubscriptionCard({ plan, status, currentPeriodEnd, cancelAtPeriodEnd, onManage }: SubscriptionCardProps) {
    const statusInfo = STATUS_LABELS[status] ?? { label: status, color: "text-muted-foreground" };
    const renewDate = currentPeriodEnd ? new Date(currentPeriodEnd).toLocaleDateString() : "—";

    return (
        <div className="rounded-xl border border-border bg-card p-6 space-y-4">
            <span className="text-lg font-semibold">📋 Suscripción</span>

            {status === "past_due" && (
                <div className="rounded-lg bg-yellow-50 border border-yellow-200 p-3 text-sm text-yellow-800">
                    ⚠️ <strong>Pago fallido.</strong> Actualiza tu método de pago para mantener el acceso.
                </div>
            )}

            <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Plan</span>
                    <span className="font-medium capitalize">{plan}</span>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Estado</span>
                    <span className={`font-medium ${statusInfo.color}`}>{statusInfo.label}</span>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Precio</span>
                    <span className="font-medium">$3 / mes</span>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted-foreground">{cancelAtPeriodEnd ? "Cancela el" : "Próximo pago"}</span>
                    <span className="font-medium">{renewDate}</span>
                </div>
            </div>

            <button
                onClick={onManage}
                className="w-full px-4 py-2 text-sm rounded-lg border border-border hover:bg-muted transition-colors"
            >
                Gestionar en Stripe Portal →
            </button>
        </div>
    );
}
