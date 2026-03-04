import { NextResponse } from "next/server";
// Fix E: firebase-admin.ts exporta instancias directas (adminAuth, adminDb), no funciones factory
import { adminAuth, adminDb, ADMIN_EMAILS } from "./firebase-admin";

export interface AuthUser {
  uid: string;
  email: string;
  role: "user" | "admin";
}

/**
 * Verify Firebase ID token from Authorization header.
 * Returns the authenticated user or a 401 response.
 */
export async function verifyAuth(
  request: Request
): Promise<AuthUser | NextResponse> {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return NextResponse.json(
      { error: "Missing Authorization header" },
      { status: 401 }
    );
  }

  const idToken = authHeader.slice(7);

  try {
    const decoded = await adminAuth.verifyIdToken(idToken);
    const uid = decoded.uid;
    const email = decoded.email ?? "";

    // Auto-promote admins por email allowlist
    if (ADMIN_EMAILS.includes(email.toLowerCase())) {
      await adminDb.collection("users").doc(uid).set(
        {
          email,
          displayName: decoded.name ?? "",
          role: "admin",
          updatedAt: new Date(),
        },
        { merge: true }
      );
      return { uid, email, role: "admin" };
    }

    // Fetch role from Firestore
    const db = adminDb;
    const userDoc = await db.collection("users").doc(uid).get();
    let role: "user" | "admin" = "user";

    if (userDoc.exists) {
      role = userDoc.data()?.role === "admin" ? "admin" : "user";
    } else {
      // First login: create user document
      await db.collection("users").doc(uid).set({
        email,
        displayName: decoded.name ?? "",
        role: "user",
        stripeCustomerId: null,
        createdAt: new Date(),
        updatedAt: new Date(),
      });
    }

    return { uid, email, role };
  } catch {
    return NextResponse.json({ error: "Invalid token" }, { status: 401 });
  }
}

/**
 * Verify that the user has admin role.
 */
export async function verifyAdmin(
  request: Request
): Promise<AuthUser | NextResponse> {
  const result = await verifyAuth(request);
  if (result instanceof NextResponse) return result;

  if (result.role !== "admin") {
    return NextResponse.json({ error: "Admin access required" }, { status: 403 });
  }

  return result;
}

/**
 * Helper estricto para rutas protegidas.
 */
export async function requireAuth(
  request: Request
): Promise<{ user: AuthUser } | { response: NextResponse }> {
  const result = await verifyAuth(request);
  if (result instanceof NextResponse) {
    return { response: result };
  }
  return { user: result };
}

/**
 * Helper estricto para rutas admin.
 */
export async function requireAdmin(
  request: Request
): Promise<{ user: AuthUser } | { response: NextResponse }> {
  const result = await verifyAdmin(request);
  if (result instanceof NextResponse) {
    return { response: result };
  }
  return { user: result };
}
