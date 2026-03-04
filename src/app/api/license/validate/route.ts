/**
 * POST /api/license/validate
 * Llamado por GIMO Server para validar una license key.
 * NO requiere Firebase auth — usa la license key directamente.
 */
import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/firebase-admin";
import { hashLicenseKey, signLicenseJwt } from "@/lib/license";
import {
  applyEntitlementDecision,
  evaluateLicenseEntitlement,
} from "@/lib/entitlement";
import { Timestamp } from "firebase-admin/firestore";

export const runtime = "nodejs";

// ---------------------------------------------------------------------------
// Rate limiting por IP — defensa en profundidad
// ---------------------------------------------------------------------------
const RATE_WINDOW_MS = 60_000;  // 1 minuto
const RATE_MAX_REQUESTS = 10;   // máx 10 intentos por minuto por IP

const rateBuckets = new Map<string, { count: number; resetAt: number }>();

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const bucket = rateBuckets.get(ip);
  if (!bucket || now > bucket.resetAt) {
    rateBuckets.set(ip, { count: 1, resetAt: now + RATE_WINDOW_MS });
    return false;
  }
  bucket.count++;
  return bucket.count > RATE_MAX_REQUESTS;
}

// Limpieza periódica para evitar memory leak (cada 5 min)
setInterval(() => {
  const now = Date.now();
  for (const [ip, bucket] of rateBuckets) {
    if (now > bucket.resetAt) rateBuckets.delete(ip);
  }
}, 5 * 60_000);

export async function POST(req: NextRequest) {
  try {
    // Rate limit por IP
    const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
      ?? req.headers.get("x-real-ip")
      ?? "unknown";
    if (isRateLimited(ip)) {
      return NextResponse.json(
        { valid: false, error: "Too many requests — try again later" },
        { status: 429 }
      );
    }

    const body = await req.json();
    const { licenseKey, machineFingerprint, machineLabel, os, hostname } = body;

    if (!licenseKey || !machineFingerprint) {
      return NextResponse.json({ valid: false, error: "licenseKey and machineFingerprint required" }, { status: 400 });
    }

    // 1. Buscar licencia por keyHash
    const keyHash = hashLicenseKey(licenseKey);
    const licQuery = await adminDb.collection("licenses")
      .where("keyHash", "==", keyHash)
      .limit(1)
      .get();

    if (licQuery.empty) {
      return NextResponse.json({ valid: false, error: "Invalid license key" }, { status: 401 });
    }

    const licDoc = licQuery.docs[0];
    const lic = licDoc.data();
    const licenseId = licDoc.id;

    // 2. Entitlement policy (fuente única de verdad)
    const entitlement = await evaluateLicenseEntitlement(licenseId, lic);
    if (!entitlement.allowed) {
      await applyEntitlementDecision(licenseId, lic.status, entitlement);

      return NextResponse.json({ valid: false, error: entitlement.reason }, { status: 403 });
    }

    // Auto-reconciliación por seguridad en caliente
    await applyEntitlementDecision(licenseId, lic.status, entitlement);

    // 3. Contar activaciones activas
    const activQuery = await adminDb.collection("activations")
      .where("licenseId", "==", licenseId)
      .where("status", "==", "active")
      .get();

    const existingActiv = activQuery.docs.find(
      (d) => d.data().machineFingerprint === machineFingerprint
    );

    if (existingActiv) {
      // Máquina ya registrada — actualizar heartbeat
      await existingActiv.ref.update({ lastHeartbeat: Timestamp.now() });
    } else if (activQuery.size >= lic.maxInstallations) {
      return NextResponse.json({
        valid: false,
        error: `Installation limit reached (${activQuery.size}/${lic.maxInstallations})`,
      }, { status: 403 });
    } else {
      // Nueva activación
      await adminDb.collection("activations").add({
        licenseId,
        machineFingerprint,
        machineLabel: machineLabel ?? `${os} - ${hostname}`,
        os: os ?? "unknown",
        hostname: hostname ?? "unknown",
        activatedAt: Timestamp.now(),
        lastHeartbeat: Timestamp.now(),
        status: "active",
      });
    }

    // 4. Firmar JWT Ed25519
    const activeCount = existingActiv ? activQuery.size : activQuery.size + 1;
    const expiresAt = lic.lifetime ? null : lic.expiresAt?.toDate()?.toISOString() ?? null;

    const token = await signLicenseJwt({
      sub: lic.userId,
      lic: licenseId,
      plan: lic.plan,
      max: lic.maxInstallations,
      mid: machineFingerprint,
      grace: 7,
      lifetime: lic.lifetime ?? false,
    });

    return NextResponse.json({
      valid: true,
      token,
      plan: lic.plan,
      expiresAt,
      isLifetime: lic.lifetime ?? false,
      activeInstallations: activeCount,
      maxInstallations: lic.maxInstallations,
    });
  } catch (err: unknown) {
    console.error("[license/validate]", err);
    return NextResponse.json({ valid: false, error: "Internal server error" }, { status: 500 });
  }
}
