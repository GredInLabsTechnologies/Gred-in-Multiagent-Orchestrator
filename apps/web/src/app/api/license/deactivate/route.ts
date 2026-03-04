/**
 * POST /api/license/deactivate
 * Libera un slot de instalación.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { requireAuth } from "@/lib/auth-middleware";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const auth = await requireAuth(req);
  if ("response" in auth) return auth.response;
  const user = auth.user;

  const { activationId } = await req.json();
  if (!activationId) return NextResponse.json({ error: "activationId required" }, { status: 400 });

  const activRef = adminDb.collection("activations").doc(activationId);
  const activDoc = await activRef.get();
  if (!activDoc.exists) return NextResponse.json({ error: "Activation not found" }, { status: 404 });

  // Verificar que la licencia pertenece al usuario
  const lic = await adminDb.collection("licenses").doc(activDoc.data()!.licenseId).get();
  if (!lic.exists || lic.data()!.userId !== user.uid) {
    if (user.role !== "admin") {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }
  }

  await activRef.update({ status: "deactivated" });
  return NextResponse.json({ success: true });
}
