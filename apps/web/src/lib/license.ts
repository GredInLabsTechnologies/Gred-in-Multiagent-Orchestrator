/**
 * GIMO License Utilities — Server-side only
 * Generación de license keys, firma JWT Ed25519, hashing.
 */
import { randomBytes, createHash } from "crypto";
import { SignJWT, importPKCS8 } from "jose";
import { verifyAuth, type AuthUser } from "@/lib/auth-middleware";

// ---------------------------------------------------------------------------
// Key generation
// ---------------------------------------------------------------------------

export function generateRawLicenseKey(): string {
  return randomBytes(32).toString("base64url"); // 43 chars, URL-safe
}

export function hashLicenseKey(rawKey: string): string {
  return createHash("sha256").update(rawKey).digest("hex");
}

export function getKeyPreview(rawKey: string): string {
  return "..." + rawKey.slice(-8);
}

// ---------------------------------------------------------------------------
// JWT Ed25519 signing
// ---------------------------------------------------------------------------

export interface LicenseJwtPayload {
  sub: string;         // userId
  lic: string;         // licenseId
  plan: string;        // "standard" | "admin"
  max: number;         // maxInstallations
  mid: string;         // machineFingerprint
  grace: number;       // grace period days
  lifetime?: boolean;
}

const JWT_EXPIRY_DAYS = 30;

/**
 * Firma un JWT con Ed25519.
 * La clave privada viene de la env var LICENSE_SIGNING_PRIVATE_KEY.
 */
export async function signLicenseJwt(
  payload: LicenseJwtPayload
): Promise<string> {
  const privateKeyPem = (process.env.LICENSE_SIGNING_PRIVATE_KEY ?? "").replace(
    /\\n/g,
    "\n"
  );
  if (!privateKeyPem || privateKeyPem.includes("PLACEHOLDER")) {
    throw new Error("LICENSE_SIGNING_PRIVATE_KEY not configured");
  }

  const privateKey = await importPKCS8(privateKeyPem, "EdDSA");

  const expirySeconds = Math.floor(Date.now() / 1000) + JWT_EXPIRY_DAYS * 86400;

  return new SignJWT({ ...payload })
    .setProtectedHeader({ alg: "EdDSA" })
    .setIssuedAt()
    .setExpirationTime(expirySeconds)
    .sign(privateKey);
}

// ---------------------------------------------------------------------------
// Auth helper (compatibilidad)
// ---------------------------------------------------------------------------

import { adminDb } from "./firebase-admin";

/**
 * Verifica el Firebase ID token del header Authorization: Bearer <token>.
 * Retorna null si inválido.
 */
export async function verifyFirebaseToken(
  req: Request
): Promise<AuthUser | null> {
  const result = await verifyAuth(req);
  if (result instanceof Response) {
    return null;
  }
  return result;
}

// ---------------------------------------------------------------------------
// Pending key store (show-once UX)
// ---------------------------------------------------------------------------

export async function storePendingKey(
  uid: string,
  rawKey: string
): Promise<void> {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + 10 * 60 * 1000); // 10 min TTL
  await adminDb.collection("pending_keys").doc(uid).set({
    rawKey,
    createdAt: now,
    expiresAt,
  });
}

/**
 * Lee y elimina la pending key (show-once).
 * Retorna null si no existe o ha expirado.
 */
export async function consumePendingKey(uid: string): Promise<string | null> {
  const ref = adminDb.collection("pending_keys").doc(uid);
  const doc = await ref.get();
  if (!doc.exists) return null;
  const data = doc.data()!;
  if (data.expiresAt.toDate() < new Date()) {
    await ref.delete();
    return null;
  }
  await ref.delete();
  return data.rawKey as string;
}
