/**
 * POST /api/admin/license/revoke
 * Admin: revocar una licencia remotamente.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { requireAdmin } from "@/lib/auth-middleware";
import { Timestamp } from "firebase-admin/firestore";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
    const auth = await requireAdmin(req);
    if ("response" in auth) return auth.response;
    const actor = auth.user;

    const { licenseId } = await req.json();
    if (!licenseId) return NextResponse.json({ error: "licenseId required" }, { status: 400 });

    const licRef = adminDb.collection("licenses").doc(licenseId);
    const licDoc = await licRef.get();
    if (!licDoc.exists) return NextResponse.json({ error: "License not found" }, { status: 404 });

    // Desactivar todas las activaciones
    const activQuery = await adminDb.collection("activations")
        .where("licenseId", "==", licenseId)
        .where("status", "==", "active")
        .get();

    const batch = adminDb.batch();
    activQuery.docs.forEach((d) => batch.update(d.ref, { status: "deactivated" }));
    batch.update(licRef, { status: "revoked", revokedAt: Timestamp.now(), revokedBy: actor.uid });
    await batch.commit();

    return NextResponse.json({
        success: true,
        activationsRevoked: activQuery.size,
        message: "License revoked. GIMO Server will shut down on next heartbeat (within 24h).",
    });
}
