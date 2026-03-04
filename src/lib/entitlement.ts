/**
 * Entitlement helpers:
 * - Decide si una licencia puede emitir token
 * - Mantener consistencia entre estado de suscripción y licencia
 */
import { adminDb } from "@/lib/firebase-admin";
import { Timestamp } from "firebase-admin/firestore";

type LicenseLike = {
    status?: string;
    lifetime?: boolean;
    expiresAt?: { toDate: () => Date } | null;
};

const ALLOWED_SUBSCRIPTION_STATUSES = new Set(["active", "trialing"]);

export type LicenseStatus = "active" | "pending_payment" | "suspended" | "expired" | "revoked";

export interface EntitlementDecision {
    allowed: boolean;
    reason: string;
    nextLicenseStatus?: LicenseStatus;
    shouldDeactivateActivations: boolean;
}

export async function applyEntitlementDecision(
    licenseId: string,
    currentStatus: string | undefined,
    decision: EntitlementDecision
): Promise<void> {
    if (decision.nextLicenseStatus && decision.nextLicenseStatus !== currentStatus) {
        await setLicenseStatus(licenseId, decision.nextLicenseStatus);
    }
    if (decision.shouldDeactivateActivations) {
        await deactivateActiveActivations(licenseId, `entitlement_denied:${decision.reason}`);
    }
}

export async function setLicenseStatus(
    licenseId: string,
    status: LicenseStatus,
    extra: Record<string, unknown> = {}
): Promise<void> {
    await adminDb.collection("licenses").doc(licenseId).update({
        status,
        ...extra,
    });
}

export async function deactivateActiveActivations(
    licenseId: string,
    reason: string
): Promise<number> {
    const activQuery = await adminDb
        .collection("activations")
        .where("licenseId", "==", licenseId)
        .where("status", "==", "active")
        .get();

    if (activQuery.empty) return 0;

    const batch = adminDb.batch();
    const now = Timestamp.now();
    activQuery.docs.forEach((doc) => {
        batch.update(doc.ref, {
            status: "deactivated",
            deactivatedAt: now,
            deactivationReason: reason,
        });
    });
    await batch.commit();
    return activQuery.size;
}

function mapSubscriptionToLicenseStatus(subscriptionStatus: string | undefined): LicenseStatus {
    if (!subscriptionStatus) return "suspended";
    if (ALLOWED_SUBSCRIPTION_STATUSES.has(subscriptionStatus)) return "active";
    if (subscriptionStatus === "canceled") return "expired";
    return "suspended";
}

function isLicenseExpired(license: LicenseLike): boolean {
    if (license.lifetime) return false;
    if (!license.expiresAt) return false;
    return license.expiresAt.toDate() < new Date();
}

/**
 * Política única de entitlement para emisión de token.
 * Fail-safe: si hay inconsistencia o datos incompletos => denegar.
 */
export async function evaluateLicenseEntitlement(
    licenseId: string,
    license: LicenseLike
): Promise<EntitlementDecision> {
    const currentStatus = (license.status ?? "").toLowerCase();

    if (currentStatus === "revoked") {
        return {
            allowed: false,
            reason: "License revoked",
            nextLicenseStatus: "revoked",
            shouldDeactivateActivations: true,
        };
    }

    if (license.lifetime) {
        if (currentStatus !== "active") {
            return {
                allowed: false,
                reason: `License ${currentStatus || "inactive"}`,
                shouldDeactivateActivations: true,
            };
        }

        return {
            allowed: true,
            reason: "lifetime_active",
            nextLicenseStatus: "active",
            shouldDeactivateActivations: false,
        };
    }

    if (isLicenseExpired(license)) {
        return {
            allowed: false,
            reason: "License expired",
            nextLicenseStatus: "expired",
            shouldDeactivateActivations: true,
        };
    }

    const subQuery = await adminDb
        .collection("subscriptions")
        .where("licenseId", "==", licenseId)
        .orderBy("currentPeriodEnd", "desc")
        .limit(1)
        .get();

    if (subQuery.empty) {
        return {
            allowed: false,
            reason: "No active subscription linked to license",
            nextLicenseStatus: "suspended",
            shouldDeactivateActivations: true,
        };
    }

    const sub = subQuery.docs[0].data();
    const subscriptionStatus = (sub.status ?? "").toLowerCase();
    const nextStatusFromSubscription = mapSubscriptionToLicenseStatus(subscriptionStatus);

    if (!ALLOWED_SUBSCRIPTION_STATUSES.has(subscriptionStatus)) {
        return {
            allowed: false,
            reason: `Subscription ${subscriptionStatus || "inactive"}`,
            nextLicenseStatus: nextStatusFromSubscription,
            shouldDeactivateActivations: true,
        };
    }

    const periodEnd = sub.currentPeriodEnd?.toDate?.() as Date | undefined;
    if (!periodEnd || periodEnd < new Date()) {
        return {
            allowed: false,
            reason: "Subscription period expired",
            nextLicenseStatus: "expired",
            shouldDeactivateActivations: true,
        };
    }

    return {
        allowed: true,
        reason: "subscription_active",
        nextLicenseStatus: "active",
        shouldDeactivateActivations: false,
    };
}
