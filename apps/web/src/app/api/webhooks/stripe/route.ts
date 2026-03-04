/**
 * POST /api/webhooks/stripe
 * Compatible con Stripe API 2026-01-28.clover.
 *
 * Cambios de la API 2026:
 * - current_period_end → subscription.billing_cycle_anchor + latest_invoice.period_end
 * - Invoice.subscription → Invoice.parent.subscription_details.subscription
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
// (ADMIN_EMAILS no se usa aquí — se usa en firebase-admin.ts para auto-promote)
import { stripe } from "@/lib/stripe";
import {
  generateRawLicenseKey,
  hashLicenseKey,
  getKeyPreview,
  storePendingKey,
} from "@/lib/license";
import { deactivateActiveActivations } from "@/lib/entitlement";
import { Timestamp } from "firebase-admin/firestore";
import type Stripe from "stripe";

export const runtime = "nodejs";

// ─── Helpers ─────────────────────────────────────────────────────

/** Obtiene el ID de suscripción desde una factura (compatible con API 2026). */
function getSubscriptionIdFromInvoice(invoice: Stripe.Invoice): string | null {
  const raw = invoice.parent?.subscription_details?.subscription;
  if (!raw) return null;
  return typeof raw === "string" ? raw : raw.id;
}

/** Obtiene el period_end (unix) desde un invoice (API 2026: usa period_end de la factura). */
function getInvoicePeriodEnd(invoice: Stripe.Invoice): number {
  return invoice.period_end ?? 0;
}

// ─── Main handler ─────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  const rawBody = await req.text();
  const sig = req.headers.get("stripe-signature");
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(rawBody, sig!, webhookSecret);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("[stripe webhook] signature verification failed:", msg);
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  try {
    // Idempotencia por Stripe event.id (reintentos seguros)
    const eventRef = adminDb.collection("stripe_events").doc(event.id);
    const seen = await eventRef.get();
    if (seen.exists) {
      return NextResponse.json({ received: true, duplicate: true });
    }

    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case "invoice.paid":
        await handleInvoicePaid(event.data.object as Stripe.Invoice);
        break;
      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;
      case "customer.subscription.updated":
        await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
        break;
      case "invoice.payment_failed":
        await handlePaymentFailed(event.data.object as Stripe.Invoice);
        break;
    }

    await eventRef.set({
      type: event.type,
      created: event.created,
      processedAt: Timestamp.now(),
    });
  } catch (err: unknown) {
    console.error("[stripe webhook] handler error:", err);
    return NextResponse.json({ error: "Handler failed" }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}

// ─── Handlers ────────────────────────────────────────────────────

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const firebaseUid = session.metadata?.firebaseUid;
  if (!firebaseUid) return;

  // Fix D: Idempotency guard — evitar licencias duplicadas si Stripe reintenta el webhook
  const existing = await adminDb
    .collection("licenses")
    .where("stripeSessionId", "==", session.id)
    .limit(1)
    .get();
  if (!existing.empty) return;

  const subscriptionId =
    typeof session.subscription === "string" ? session.subscription : session.subscription?.id;
  if (!subscriptionId) return;

  // Expandir la última factura para obtener el período (API 2026)
  const subscription = await stripe.subscriptions.retrieve(subscriptionId, {
    expand: ["latest_invoice"],
  });

  const latestInvoice =
    subscription.latest_invoice && typeof subscription.latest_invoice === "object"
      ? (subscription.latest_invoice as Stripe.Invoice)
      : null;

  const periodEndUnix = latestInvoice ? getInvoicePeriodEnd(latestInvoice) : 0;
  const periodStartUnix = latestInvoice ? (latestInvoice.period_start ?? 0) : 0;
  const expiresAt = periodEndUnix > 0 ? new Date(periodEndUnix * 1000) : new Date(Date.now() + 30 * 86400 * 1000);

  const rawKey = generateRawLicenseKey();
  const keyHash = hashLicenseKey(rawKey);
  const keyPreview = getKeyPreview(rawKey);

  const licRef = await adminDb.collection("licenses").add({
    userId: firebaseUid,
    keyHash,
    keyPreview,
    plan: "standard",
    lifetime: false,
    maxInstallations: 2,
    // Solo se activa con invoice.paid
    status: "pending_payment",
    createdAt: Timestamp.now(),
    expiresAt: Timestamp.fromDate(expiresAt),
    regenerationCount: 0,
    stripeSessionId: session.id,  // Fix D: clave de idempotencia
  });

  await adminDb.collection("subscriptions").add({
    userId: firebaseUid,
    licenseId: licRef.id,
    stripeSubscriptionId: subscriptionId,
    stripePriceId: subscription.items.data[0].price.id,
    status: subscription.status,
    currentPeriodStart: Timestamp.fromDate(new Date(periodStartUnix * 1000)),
    currentPeriodEnd: Timestamp.fromDate(expiresAt),
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
  });

  await storePendingKey(firebaseUid, rawKey);
}

async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const subscriptionId = getSubscriptionIdFromInvoice(invoice);
  if (!subscriptionId) return;

  const subQuery = await adminDb
    .collection("subscriptions")
    .where("stripeSubscriptionId", "==", subscriptionId)
    .limit(1)
    .get();
  if (subQuery.empty) return;

  const subDoc = subQuery.docs[0];
  const periodEnd = getInvoicePeriodEnd(invoice);
  const newExpiry = Timestamp.fromDate(
    periodEnd > 0 ? new Date(periodEnd * 1000) : new Date(Date.now() + 30 * 86400 * 1000)
  );

  const subscription = await stripe.subscriptions.retrieve(subscriptionId);

  const batch = adminDb.batch();
  batch.update(subDoc.ref, {
    status: subscription.status,
    currentPeriodEnd: newExpiry,
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
  });

  const nextLicenseStatus = ["active", "trialing"].includes(subscription.status)
    ? "active"
    : "suspended";

  batch.update(adminDb.collection("licenses").doc(subDoc.data().licenseId), {
    status: nextLicenseStatus,
    expiresAt: newExpiry,
  });
  await batch.commit();

  if (nextLicenseStatus !== "active") {
    await deactivateActiveActivations(subDoc.data().licenseId, `invoice_paid_but_subscription_${subscription.status}`);
  }
}

async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const subQuery = await adminDb
    .collection("subscriptions")
    .where("stripeSubscriptionId", "==", subscription.id)
    .limit(1)
    .get();
  if (subQuery.empty) return;

  const subDoc = subQuery.docs[0];
  const batch = adminDb.batch();
  batch.update(subDoc.ref, { status: "canceled" });
  batch.update(
    adminDb.collection("licenses").doc(subDoc.data().licenseId),
    { status: "expired" }
  );
  await batch.commit();

  await deactivateActiveActivations(subDoc.data().licenseId, "subscription_deleted");
}

async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  const subQuery = await adminDb
    .collection("subscriptions")
    .where("stripeSubscriptionId", "==", subscription.id)
    .limit(1)
    .get();
  if (subQuery.empty) return;

  const subDoc = subQuery.docs[0];
  await subDoc.ref.update({
    status: subscription.status,
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
  });

  const nextLicenseStatus = ["active", "trialing"].includes(subscription.status)
    ? "active"
    : subscription.status === "canceled"
      ? "expired"
      : "suspended";

  await adminDb.collection("licenses").doc(subDoc.data().licenseId).update({
    status: nextLicenseStatus,
  });

  if (nextLicenseStatus !== "active") {
    await deactivateActiveActivations(
      subDoc.data().licenseId,
      `subscription_updated_${subscription.status}`
    );
  }
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  const subscriptionId = getSubscriptionIdFromInvoice(invoice);
  if (!subscriptionId) return;

  const subQuery = await adminDb
    .collection("subscriptions")
    .where("stripeSubscriptionId", "==", subscriptionId)
    .limit(1)
    .get();
  if (subQuery.empty) return;

  const subDoc = subQuery.docs[0];
  const licenseId = subDoc.data().licenseId;

  const batch = adminDb.batch();
  batch.update(subDoc.ref, { status: "past_due" });
  batch.update(adminDb.collection("licenses").doc(licenseId), { status: "suspended" });
  await batch.commit();

  await deactivateActiveActivations(licenseId, "invoice_payment_failed");
}
