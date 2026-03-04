/**
 * POST /api/billing/portal
 * Crea una Stripe Customer Portal session para gestionar la suscripción.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { requireAuth } from "@/lib/auth-middleware";
import { stripe } from "@/lib/stripe";

export const runtime = "nodejs";

const BASE_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://gimo-web.vercel.app";

export async function POST(req: NextRequest) {
    const auth = await requireAuth(req);
    if ("response" in auth) return auth.response;
    const user = auth.user;

    // Obtener stripeCustomerId del usuario
    const userDoc = await adminDb.collection("users").doc(user.uid).get();
    const stripeCustomerId: string | undefined = userDoc.data()?.stripeCustomerId;

    if (!stripeCustomerId) {
        return NextResponse.json(
            { error: "No billing account found. Please subscribe first." },
            { status: 404 }
        );
    }

    const session = await stripe.billingPortal.sessions.create({
        customer: stripeCustomerId,
        return_url: `${BASE_URL}/account`,
    });

    return NextResponse.json({ url: session.url });
}
