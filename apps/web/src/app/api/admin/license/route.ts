/**
 * POST /api/admin/license   — Admin: crear licencia vitalicia
 * GET  /api/admin/license   — Admin: listar todas las licencias
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { generateRawLicenseKey, hashLicenseKey, getKeyPreview, storePendingKey } from "@/lib/license";
import { requireAdmin } from "@/lib/auth-middleware";
import { Timestamp } from "firebase-admin/firestore";

export const runtime = "nodejs";

// ─────────────────────────────────────────
// POST — Crear licencia vitalicia
// ─────────────────────────────────────────
export async function POST(req: NextRequest) {
  const auth = await requireAdmin(req);
  if ("response" in auth) return auth.response;
  const actor = auth.user;

  const { targetEmail, maxInstallations = 999 } = await req.json();
  if (!targetEmail) {
    return NextResponse.json({ error: "targetEmail required" }, { status: 400 });
  }

  // Buscar usuario por email
  let targetUid: string;
  try {
    const userRecord = await (await import("@/lib/firebase-admin")).adminAuth.getUserByEmail(targetEmail);
    targetUid = userRecord.uid;
  } catch {
    return NextResponse.json({ error: "User not found" }, { status: 404 });
  }

  const rawKey = generateRawLicenseKey();
  const keyHash = hashLicenseKey(rawKey);
  const keyPreview = getKeyPreview(rawKey);

  const licRef = await adminDb.collection("licenses").add({
    userId: targetUid,
    keyHash,
    keyPreview,
    plan: "admin",
    lifetime: true,
    maxInstallations,
    status: "active",
    createdAt: Timestamp.now(),
    expiresAt: null,
    regenerationCount: 0,
    createdByAdmin: actor.uid,
  });

  // Guardar pending key (show-once)
  await storePendingKey(targetUid, rawKey);

  return NextResponse.json({
    success: true,
    licenseId: licRef.id,
    rawKey,           // solo esta vez
    keyPreview,
    note: "Store this key securely — it will not be shown again.",
  });
}

// ─────────────────────────────────────────
// GET — Listar licencias (paginado)
// ─────────────────────────────────────────
export async function GET(req: NextRequest) {
  const auth = await requireAdmin(req);
  if ("response" in auth) return auth.response;

  const url = new URL(req.url);
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "50"), 200);
  // Fix F: cursor-based pagination en vez de limit+offset (O(N) en Firestore)
  // El cliente pasa el ID del último documento recibido como "cursor"
  const cursorId = url.searchParams.get("cursor") ?? null;

  let query: FirebaseFirestore.Query = adminDb
    .collection("licenses")
    .orderBy("createdAt", "desc")
    .limit(limit);

  if (cursorId) {
    const cursorDoc = await adminDb.collection("licenses").doc(cursorId).get();
    if (cursorDoc.exists) {
      query = query.startAfter(cursorDoc);
    }
  }

  const snapshot = await query.get();
  const docs = snapshot.docs;

  const licenses = await Promise.all(
    docs.map(async (d) => {
      const data = d.data();
      // Contar activaciones activas
      const activCount = (
        await adminDb.collection("activations")
          .where("licenseId", "==", d.id)
          .where("status", "==", "active")
          .get()
      ).size;

      // Info de usuario
      let email = "unknown";
      try {
        const uDoc = await adminDb.collection("users").doc(data.userId).get();
        email = uDoc.data()?.email ?? "unknown";
      } catch { }

      return {
        id: d.id,
        email,
        plan: data.plan,
        status: data.status,
        lifetime: data.lifetime,
        maxInstallations: data.maxInstallations,
        activeInstallations: activCount,
        keyPreview: data.keyPreview,
        createdAt: data.createdAt?.toDate()?.toISOString(),
        expiresAt: data.expiresAt?.toDate()?.toISOString() ?? null,
      };
    })
  );

  // nextCursor: ID del último doc de esta página (para solicitar la siguiente)
  const nextCursor = docs.length === limit ? docs[docs.length - 1].id : null;
  return NextResponse.json({ licenses, total: snapshot.size, nextCursor });
}
