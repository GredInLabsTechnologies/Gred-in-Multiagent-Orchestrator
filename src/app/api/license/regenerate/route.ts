/**
 * POST /api/license/regenerate
 * Regenera la license key del usuario. Rate limit: 1 por 24h.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { generateRawLicenseKey, hashLicenseKey, getKeyPreview, storePendingKey } from "@/lib/license";
import { requireAuth } from "@/lib/auth-middleware";
import { Timestamp } from "firebase-admin/firestore";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const auth = await requireAuth(req);
  if ("response" in auth) return auth.response;
  const user = auth.user;

  // Buscar licencia activa del usuario
  const licQuery = await adminDb.collection("licenses")
    .where("userId", "==", user.uid)
    .where("status", "==", "active")
    .limit(1)
    .get();

  if (licQuery.empty) {
    return NextResponse.json({ error: "No active license" }, { status: 404 });
  }

  const licDoc = licQuery.docs[0];
  const lic = licDoc.data();

  // Rate limit: 1 regeneración por 24h
  if (lic.lastRegeneratedAt) {
    const last = lic.lastRegeneratedAt.toDate() as Date;
    const hoursSince = (Date.now() - last.getTime()) / 3600000;
    if (hoursSince < 24) {
      return NextResponse.json({
        error: `Rate limit: wait ${Math.ceil(24 - hoursSince)}h before regenerating again`,
      }, { status: 429 });
    }
  }

  // Generar nueva key
  const rawKey = generateRawLicenseKey();
  const keyHash = hashLicenseKey(rawKey);
  const keyPreview = getKeyPreview(rawKey);

  // Desactivar TODAS las activaciones existentes
  const activQuery = await adminDb.collection("activations")
    .where("licenseId", "==", licDoc.id)
    .where("status", "==", "active")
    .get();

  const batch = adminDb.batch();
  activQuery.docs.forEach((d) => batch.update(d.ref, { status: "deactivated" }));

  // Actualizar licencia con nueva key
  batch.update(licDoc.ref, {
    keyHash,
    keyPreview,
    lastRegeneratedAt: Timestamp.now(),
    regenerationCount: (lic.regenerationCount ?? 0) + 1,
  });

  await batch.commit();

  // Guardar pending key (show-once)
  await storePendingKey(user.uid, rawKey);

  return NextResponse.json({
    success: true,
    rawKey,
    keyPreview,
    activationsReset: activQuery.size,
    note: "All previous activations have been deactivated. Set up GIMO Server with this new key.",
  });
}
