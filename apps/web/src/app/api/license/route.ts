/**
 * GET /api/license
 * Devuelve info de la licencia activa del usuario.
 * Si existe una pending_key (key aún no vista), la incluye y la elimina.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { consumePendingKey } from "@/lib/license";
import { requireAuth } from "@/lib/auth-middleware";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const auth = await requireAuth(req);
  if ("response" in auth) return auth.response;
  const user = auth.user;

  // Licencia activa del usuario
  const licQuery = await adminDb.collection("licenses")
    .where("userId", "==", user.uid)
    .orderBy("createdAt", "desc")
    .limit(1)
    .get();

  if (licQuery.empty) {
    return NextResponse.json({ license: null });
  }

  const licDoc = licQuery.docs[0];
  const lic = licDoc.data();

  // Contar activaciones activas
  const activQuery = await adminDb.collection("activations")
    .where("licenseId", "==", licDoc.id)
    .where("status", "==", "active")
    .get();

  const activations = activQuery.docs.map((d) => ({
    id: d.id,
    machineLabel: d.data().machineLabel,
    os: d.data().os,
    hostname: d.data().hostname,
    activatedAt: d.data().activatedAt?.toDate()?.toISOString(),
    lastHeartbeat: d.data().lastHeartbeat?.toDate()?.toISOString(),
  }));

  // Suscripción activa
  const subQuery = await adminDb.collection("subscriptions")
    .where("userId", "==", user.uid)
    .orderBy("currentPeriodEnd", "desc")
    .limit(1)
    .get();

  const subscription = subQuery.empty ? null : (() => {
    const s = subQuery.docs[0].data();
    return {
      status: s.status,
      currentPeriodEnd: s.currentPeriodEnd?.toDate()?.toISOString(),
      cancelAtPeriodEnd: s.cancelAtPeriodEnd,
    };
  })();

  // Pending key (show-once) — usar helper centralizado
  const rawKey = await consumePendingKey(user.uid);

  return NextResponse.json({
    license: {
      id: licDoc.id,
      plan: lic.plan,
      status: lic.status,
      lifetime: lic.lifetime,
      keyPreview: lic.keyPreview,
      maxInstallations: lic.maxInstallations,
      installationsUsed: activations.length,
      expiresAt: lic.expiresAt?.toDate()?.toISOString() ?? null,
      regenerationCount: lic.regenerationCount,
      // rawKey solo presente si hay pending key (show-once)
      ...(rawKey ? { rawKey } : {}),
    },
    activations,
    subscription,
    isAdmin: user.role === "admin",
  });
}
