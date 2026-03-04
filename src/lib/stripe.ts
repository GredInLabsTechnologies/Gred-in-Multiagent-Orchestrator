import Stripe from "stripe";

// Lazy initialization — evita error en build time si STRIPE_SECRET_KEY no está configurada
let _stripe: Stripe | null = null;

function getStripe(): Stripe {
    if (_stripe) return _stripe;
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) throw new Error("STRIPE_SECRET_KEY env var not set");
    _stripe = new Stripe(key, { apiVersion: "2026-01-28.clover", typescript: true });
    return _stripe;
}

export const stripe: Stripe = new Proxy({} as Stripe, {
    get(_target, prop) {
        return (getStripe() as unknown as Record<string | symbol, unknown>)[prop];
    },
});

/** Precio mensual del plan Standard (crear en Stripe Dashboard y copiar aquí) */
export function getStandardPriceId(): string {
    const priceId = process.env.STRIPE_STANDARD_PRICE_ID ?? "";
    if (!priceId || priceId.includes("PLACEHOLDER")) {
        throw new Error("STRIPE_STANDARD_PRICE_ID env var not set or placeholder");
    }
    return priceId;
}
