/**
 * POST /api/checkout
 * Crea una Stripe Checkout Session para suscripción Standard.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { requireAuth } from "@/lib/auth-middleware";
import { stripe, getStandardPriceId } from "@/lib/stripe";

export const runtime = "nodejs";

const BASE_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://gimo-web.vercel.app";

export async function POST(req: NextRequest) {
  const auth = await requireAuth(req);
  if ("response" in auth) return auth.response;
  const user = auth.user;

  const standardPriceId = getStandardPriceId();

  // Obtener o crear Stripe Customer
  const userDoc = await adminDb.collection("users").doc(user.uid).get();
  let stripeCustomerId: string | undefined = userDoc.data()?.stripeCustomerId;

  if (!stripeCustomerId) {
    const customer = await stripe.customers.create({
      email: user.email,
      metadata: { firebaseUid: user.uid },
    });
    stripeCustomerId = customer.id;
    await adminDb.collection("users").doc(user.uid).set(
      { stripeCustomerId, email: user.email },
      { merge: true }
    );
  }

  // Crear Checkout Session
  const session = await stripe.checkout.sessions.create({
    customer: stripeCustomerId,
    mode: "subscription",
    line_items: [{ price: standardPriceId, quantity: 1 }],
    metadata: { firebaseUid: user.uid },
    success_url: `${BASE_URL}/account?checkout=success`,
    cancel_url: `${BASE_URL}/account?checkout=canceled`,
    allow_promotion_codes: true,
  });

  return NextResponse.json({ url: session.url });
}
