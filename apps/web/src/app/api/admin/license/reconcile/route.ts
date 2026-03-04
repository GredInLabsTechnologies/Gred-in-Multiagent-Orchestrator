/**
 * POST /api/admin/license/reconcile
 * Admin: revalida consistencia de entitlement en licencias no-lifetime.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { requireAdmin } from "@/lib/auth-middleware";
import {
    applyEntitlementDecision,
    evaluateLicenseEntitlement,
} from "@/lib/entitlement";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
    const auth = await requireAdmin(req);
    if ("response" in auth) return auth.response;

    const body = await req.json().catch(() => ({}));
    const limit = Math.min(Math.max(Number(body?.limit ?? 200), 1), 1000);

    const snapshot = await adminDb
        .collection("licenses")
        .where("lifetime", "==", false)
        .orderBy("createdAt", "desc")
        .limit(limit)
        .get();

    let checked = 0;
    let changed = 0;
    let denied = 0;

    for (const doc of snapshot.docs) {
        const license = doc.data();
        const decision = await evaluateLicenseEntitlement(doc.id, license);
        checked++;

        if (!decision.allowed) denied++;
        const willChangeStatus =
            !!decision.nextLicenseStatus && decision.nextLicenseStatus !== license.status;

        if (willChangeStatus || decision.shouldDeactivateActivations) {
            await applyEntitlementDecision(doc.id, license.status, decision);
            changed++;
        }
    }

    return NextResponse.json({
        success: true,
        checked,
        changed,
        denied,
        note: "Entitlement reconciliation completed",
    });
}
