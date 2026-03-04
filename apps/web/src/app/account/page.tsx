"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAuth, onAuthStateChanged, signOut, type User } from "firebase/auth";
import { LicenseKeyCard } from "@/components/license-key-card";
import { InstallationManager } from "@/components/installation-manager";
import { SubscriptionCard } from "@/components/subscription-card";
import { QuickSetupGuide } from "@/components/quick-setup-guide";
import { AdminPanel } from "@/components/admin-panel";
import { LockedCard } from "@/components/locked-card";

// ─── Types ──────────────────────────────────────────────────────

interface LicenseData {
  id: string;
  plan: string;
  status: string;
  lifetime: boolean;
  keyPreview: string;
  maxInstallations: number;
  installationsUsed: number;
  expiresAt?: string | null;
  regenerationCount: number;
  rawKey?: string;  // show-once
}

interface Activation {
  id: string;
  machineLabel: string;
  os: string;
  hostname: string;
  activatedAt?: string;
  lastHeartbeat?: string;
}

interface SubscriptionData {
  status: string;
  currentPeriodEnd?: string;
  cancelAtPeriodEnd?: boolean;
}

interface AccountState {
  license: LicenseData | null;
  activations: Activation[];
  subscription: SubscriptionData | null;
  isAdmin: boolean;
  adminLicenses: unknown[];
}

// ─── Helpers ────────────────────────────────────────────────────

async function getIdToken(user: User): Promise<string> {
  return user.getIdToken();
}

async function apiFetch(user: User, path: string, options: RequestInit = {}) {
  const token = await getIdToken(user);
  const res = await fetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Page ───────────────────────────────────────────────────────

export default function AccountPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<AccountState>({
    license: null, activations: [], subscription: null, isAdmin: false, adminLicenses: [],
  });
  const [checkoutSuccess, setCheckoutSuccess] = useState(false);
  const router = useRouter();

  // Leer query param sin useSearchParams (evita Suspense boundary requirement)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setCheckoutSuccess(params.get("checkout") === "success");
  }, []);

  // Auth listener
  useEffect(() => {
    const auth = getAuth();
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u);
      if (!u) router.push("/");
    });
    return unsub;
  }, [router]);

  // Load license data
  async function loadData(u: User) {
    setLoading(true);
    try {
      const res = await apiFetch(u, "/api/license");
      let adminLicenses: unknown[] = [];
      if (res.isAdmin) {
        const adminRes = await apiFetch(u, "/api/admin/license");
        adminLicenses = adminRes.licenses ?? [];
      }
      setData({ ...res, adminLicenses });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user) loadData(user);
  }, [user]);

  // ── Handlers ──────────────────────────────────────────────────

  async function handleCheckout() {
    if (!user) return;
    const res = await apiFetch(user, "/api/checkout", { method: "POST" });
    window.location.href = res.url;
  }

  async function handleRegenerate() {
    if (!user) return;
    await apiFetch(user, "/api/license/regenerate", { method: "POST" });
    await loadData(user);
  }

  async function handleDeactivate(activationId: string) {
    if (!user) return;
    await apiFetch(user, "/api/license/deactivate", { method: "POST", body: JSON.stringify({ activationId }) });
    await loadData(user);
  }

  async function handleManagePortal() {
    if (!user) return;
    const res = await apiFetch(user, "/api/billing/portal", { method: "POST" });
    window.location.href = res.url;
  }

  async function handleCreateLifetime(email: string, maxInstallations: number) {
    if (!user) throw new Error("Not authenticated");
    return apiFetch(user, "/api/admin/license", {
      method: "POST",
      body: JSON.stringify({ targetEmail: email, maxInstallations }),
    });
  }

  async function handleRevoke(licenseId: string) {
    if (!user) return;
    await apiFetch(user, "/api/admin/license/revoke", { method: "POST", body: JSON.stringify({ licenseId }) });
    await loadData(user);
  }

  // ── Render ────────────────────────────────────────────────────

  if (!user || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-t-2 border-emerald-500 border-solid rounded-full animate-spin"></div>
          <div className="text-emerald-500/50 text-xs font-mono tracking-widest uppercase">Verificando Credenciales...</div>
        </div>
      </div>
    );
  }

  const { license, activations, subscription, isAdmin, adminLicenses } = data;

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black text-slate-200">
      {/* Header */}
      <header className="border-b border-white/5 bg-black/20 backdrop-blur-md px-6 py-4 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center font-bold text-black text-xs">G</div>
          <span className="font-bold text-lg tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">GIMO</span>
        </div>
        <div className="flex items-center gap-6">
          <div className="hidden sm:flex flex-col items-end">
            <span className="text-xs font-medium text-slate-400 uppercase tracking-tighter">Cuenta Activa</span>
            <span className="text-xs text-emerald-400/80 font-mono">{user.email}</span>
          </div>
          <button
            onClick={() => signOut(getAuth())}
            className="px-4 py-1.5 rounded-full border border-white/10 text-xs font-medium hover:bg-white/5 transition-all"
          >
            Salir
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <h1 className="text-2xl font-bold">Mi Cuenta</h1>

        {checkoutSuccess && (
          <div className="rounded-lg bg-green-50 border border-green-200 p-4 text-green-800 text-sm">
            🎉 <strong>¡Suscripción activada!</strong> Tu clave de licencia está lista abajo.
          </div>
        )}

        {/* Sin suscripción — dashboard bloqueado */}
        {!license && (
          <>
            {/* Bienvenida con badge Plan: Free */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">{user.email}</p>
              </div>
              <span className="text-xs font-semibold px-3 py-1 rounded-full bg-muted text-muted-foreground border border-border">
                Plan: Free
              </span>
            </div>

            {/* Card Clave de Licencia — bloqueado */}
            <LockedCard
              title="🔑 Clave de Licencia"
              ctaText="Desbloquea tu clave — $3/mes"
              onAction={handleCheckout}
            >
              <div className="space-y-3">
                <div className="flex items-center gap-3 rounded-lg bg-muted/50 border border-border px-4 py-3 font-mono text-sm tracking-widest text-muted-foreground">
                  XXXX-XXXX-XXXX-XXXX
                </div>
                <div className="flex gap-2">
                  <div className="h-8 w-24 rounded bg-muted/40 border border-border" />
                  <div className="h-8 w-28 rounded bg-muted/40 border border-border" />
                </div>
              </div>
            </LockedCard>

            {/* Grid 2 columnas: Suscripción + Instalaciones */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Card Suscripción — bloqueado */}
              <LockedCard
                title="💳 Suscripción"
                ctaText="Activar plan Standard"
                onAction={handleCheckout}
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Estado</span>
                    <span className="text-muted-foreground">Sin plan activo</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Plan</span>
                    <span className="text-muted-foreground">—</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Renovación</span>
                    <span className="text-muted-foreground">—</span>
                  </div>
                  <div className="h-8 w-full rounded bg-muted/40 border border-border mt-2" />
                </div>
              </LockedCard>

              {/* Card Instalaciones — bloqueado */}
              <LockedCard
                title="🖥 Instalaciones"
                ctaText="Suscríbete para instalar"
                onAction={handleCheckout}
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Usadas</span>
                    <span className="text-muted-foreground">0 / 2</span>
                  </div>
                  <div className="space-y-2 mt-1">
                    <div className="flex items-center gap-2 rounded-lg border border-dashed border-border p-2">
                      <div className="w-2 h-2 rounded-full bg-muted" />
                      <span className="text-xs text-muted-foreground">Slot vacío</span>
                    </div>
                    <div className="flex items-center gap-2 rounded-lg border border-dashed border-border p-2">
                      <div className="w-2 h-2 rounded-full bg-muted" />
                      <span className="text-xs text-muted-foreground">Slot vacío</span>
                    </div>
                  </div>
                </div>
              </LockedCard>
            </div>

            {/* Card Setup Guide — bloqueado */}
            <LockedCard
              title="🚀 Guía de instalación rápida"
              ctaText="Activa tu plan para ver los comandos"
              onAction={handleCheckout}
            >
              <div className="space-y-2 font-mono text-xs">
                <div className="rounded bg-muted/60 px-3 py-2 text-muted-foreground">
                  npm install -g gimo-cli
                </div>
                <div className="rounded bg-muted/60 px-3 py-2 text-muted-foreground">
                  gimo auth --key XXXX-XXXX-XXXX-XXXX
                </div>
                <div className="rounded bg-muted/60 px-3 py-2 text-muted-foreground">
                  gimo start
                </div>
              </div>
            </LockedCard>

            {/* Banner CTA inferior */}
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="space-y-1 text-center sm:text-left">
                <p className="font-semibold text-foreground">Plan Standard — $3/mes</p>
                <ul className="text-xs text-muted-foreground space-y-0.5">
                  <li>✅ Clave de licencia personal</li>
                  <li>✅ Hasta 2 instalaciones simultáneas</li>
                  <li>✅ Soporte offline con JWT cache cifrado</li>
                  <li>✅ Cancela cuando quieras</li>
                </ul>
              </div>
              <button
                onClick={handleCheckout}
                className="shrink-0 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-semibold hover:bg-primary/90 transition-colors shadow"
              >
                Comenzar ahora — $3/mes
              </button>
            </div>
          </>
        )}

        {/* Con licencia */}
        {license && (
          <>
            <LicenseKeyCard
              rawKey={license.rawKey}
              keyPreview={license.keyPreview}
              onRegenerate={handleRegenerate}
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <SubscriptionCard
                plan={license.plan}
                status={subscription?.status ?? license.status}
                currentPeriodEnd={subscription?.currentPeriodEnd}
                cancelAtPeriodEnd={subscription?.cancelAtPeriodEnd}
                onManage={handleManagePortal}
              />

              <InstallationManager
                activations={activations}
                maxInstallations={license.maxInstallations}
                onDeactivate={handleDeactivate}
              />
            </div>

            <QuickSetupGuide
              licenseKey={license.rawKey}
              keyPreview={license.keyPreview}
            />
          </>
        )}

        {/* Panel Admin */}
        {isAdmin && (
          <AdminPanel
            licenses={adminLicenses as Parameters<typeof AdminPanel>[0]["licenses"]}
            onCreateLifetime={handleCreateLifetime}
            onRevoke={handleRevoke}
          />
        )}
      </main>
    </div>
  );
}
