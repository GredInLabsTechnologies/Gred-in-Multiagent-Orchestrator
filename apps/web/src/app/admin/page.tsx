"use client";

import { useEffect, useState, useCallback } from "react";
import { onAuthStateChanged, User, signOut } from "firebase/auth";
import { auth } from "@/lib/firebase";
import {
  Shield,
  Users,
  Key,
  Zap,
  LogOut,
  Copy,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

interface LicenseEntry {
  id: string;
  email: string;
  plan: string;
  status: string;
  maxInstallations: number;
  activeInstallations: number;
  isLifetime: boolean;
  createdAt: string;
  expiresAt: string | null;
}

interface Stats {
  totalLicenses: number;
  activeLicenses: number;
  totalInstallations: number;
}

async function getIdToken(user: User): Promise<string> {
  return user.getIdToken();
}

export default function AdminPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [licenses, setLicenses] = useState<LicenseEntry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [targetEmail, setTargetEmail] = useState("");
  const [creating, setCreating] = useState(false);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

  const router = useRouter();

  const fetchLicenses = useCallback(async (currentUser: User) => {
    try {
      const token = await getIdToken(currentUser);
      const res = await fetch("/api/admin/license", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 403) {
        router.push("/account");
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      setLicenses(data.licenses);
      // Fix C: la API devuelve {licenses, total} — no hay campo stats. Derivar stats del array.
      const activeLicenses = (data.licenses as LicenseEntry[]).filter(
        (l) => l.status === "active"
      ).length;
      const totalInstallations = (data.licenses as LicenseEntry[]).reduce(
        (sum, l) => sum + l.activeInstallations,
        0
      );
      setStats({
        totalLicenses: data.total,
        activeLicenses,
        totalInstallations,
      });
    } catch {
      // handle error
    }
  }, [router]);

  useEffect(() => {
    if (!auth) return;
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      if (!currentUser) {
        router.push("/empezar-gratis");
        return;
      }
      setUser(currentUser);
      setLoading(false);
      fetchLicenses(currentUser);
    });
    return () => unsubscribe();
  }, [router, fetchLicenses]);

  const handleCreateLicense = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user || !targetEmail.trim()) return;
    setCreating(true);
    setError(null);
    setGeneratedKey(null);

    try {
      const token = await getIdToken(user);
      const res = await fetch("/api/admin/license", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          targetEmail: targetEmail.trim(),
          maxInstallations: 999999,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error);
        return;
      }
      // Fix B: la API devuelve rawKey (no key)
      setGeneratedKey(data.rawKey);
      setTargetEmail("");
      fetchLicenses(user);
    } catch {
      setError("Error de conexion");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (licenseId: string) => {
    if (!user) return;
    setRevoking(licenseId);
    try {
      // Fix A: el endpoint de revocación es POST /api/admin/license/revoke
      const token = await getIdToken(user);
      await fetch("/api/admin/license/revoke", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ licenseId }),
      });
      fetchLicenses(user);
    } catch {
      // handle error
    } finally {
      setRevoking(null);
    }
  };

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  const handleSignOut = async () => {
    if (!auth) return;
    await signOut(auth);
    router.push("/");
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 selection:bg-emerald-500/30">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-purple-500/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-emerald-500/10 blur-[120px] rounded-full" />
      </div>

      <nav className="relative z-10 border-b border-slate-800/50 bg-slate-950/50 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 bg-gradient-to-br from-purple-400 to-emerald-600 rounded-lg flex items-center justify-center group-hover:scale-110 transition-transform">
              <Shield size={18} className="text-white" />
            </div>
            <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
              GIMO Admin
            </span>
          </Link>
          <div className="flex items-center gap-6">
            <Link
              href="/account"
              className="text-xs font-medium text-slate-400 hover:text-slate-300 transition-colors"
            >
              Mi Cuenta
            </Link>
            <span className="text-sm text-slate-400 hidden sm:inline-block">
              {user?.email}
            </span>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-2 text-xs font-medium text-red-400 hover:text-red-300 transition-colors"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </nav>

      <main className="relative z-10 max-w-5xl mx-auto px-6 py-12">
        <header className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Panel de Administracion</h1>
          <p className="text-slate-400 font-medium">
            Gestiona licencias, usuarios y suscripciones.
          </p>
        </header>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-3 gap-4 mb-10">
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 text-center">
              <p className="text-3xl font-bold text-white">{stats.totalLicenses}</p>
              <p className="text-xs text-slate-500 mt-1">Licencias Totales</p>
            </div>
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 text-center">
              <p className="text-3xl font-bold text-emerald-400">{stats.activeLicenses}</p>
              <p className="text-xs text-slate-500 mt-1">Activas</p>
            </div>
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 text-center">
              <p className="text-3xl font-bold text-blue-400">{stats.totalInstallations}</p>
              <p className="text-xs text-slate-500 mt-1">Instalaciones</p>
            </div>
          </div>
        )}

        {/* Create Lifetime License */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm mb-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-purple-500/10 rounded-lg flex items-center justify-center border border-purple-500/20">
              <Key className="text-purple-400" size={20} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">
                Crear Licencia Vitalicia
              </h2>
              <p className="text-sm text-slate-500">
                Instalaciones ilimitadas, sin expiracion.
              </p>
            </div>
          </div>

          <form onSubmit={handleCreateLicense} className="flex gap-3">
            <input
              type="email"
              value={targetEmail}
              onChange={(e) => setTargetEmail(e.target.value)}
              placeholder="email@ejemplo.com"
              required
              className="flex-1 px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20"
            />
            <button
              type="submit"
              disabled={creating}
              className="px-6 py-3 bg-purple-600 hover:bg-purple-500 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-50 flex items-center gap-2 shrink-0"
            >
              {creating ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Creando...
                </>
              ) : (
                <>
                  <Zap size={14} />
                  Crear Licencia
                </>
              )}
            </button>
          </form>

          {error && (
            <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center gap-2">
              <XCircle className="text-red-400 shrink-0" size={16} />
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}

          {generatedKey && (
            <div className="mt-4 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="text-amber-400" size={16} />
                <p className="text-sm font-semibold text-amber-300">
                  Clave generada (solo se muestra una vez)
                </p>
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 p-2 bg-slate-900/80 border border-slate-700 rounded-lg text-xs font-mono text-emerald-400 break-all select-all">
                  {generatedKey}
                </code>
                <button
                  onClick={() => copyToClipboard(generatedKey)}
                  className="p-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-colors shrink-0"
                >
                  {copied ? (
                    <CheckCircle2 size={16} className="text-white" />
                  ) : (
                    <Copy size={16} className="text-white" />
                  )}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Licenses Table */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center">
              <Users className="text-slate-400" size={20} />
            </div>
            <h2 className="text-lg font-semibold text-white">Todas las Licencias</h2>
          </div>

          {licenses.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-8">
              No hay licencias registradas.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
                    <th className="pb-3 pr-4">Email</th>
                    <th className="pb-3 pr-4">Plan</th>
                    <th className="pb-3 pr-4">Estado</th>
                    <th className="pb-3 pr-4">Inst.</th>
                    <th className="pb-3 pr-4">Tipo</th>
                    <th className="pb-3 text-right">Accion</th>
                  </tr>
                </thead>
                <tbody>
                  {licenses.map((lic) => (
                    <tr
                      key={lic.id}
                      className="border-b border-slate-800/50 hover:bg-slate-800/20"
                    >
                      <td className="py-3 pr-4 text-white font-mono text-xs">
                        {lic.email}
                      </td>
                      <td className="py-3 pr-4">
                        <span
                          className={`text-xs font-semibold ${lic.plan === "admin"
                              ? "text-purple-400"
                              : "text-blue-400"
                            }`}
                        >
                          {lic.plan}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <span
                          className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded-full ${lic.status === "active"
                              ? "bg-emerald-500/10 text-emerald-400"
                              : lic.status === "revoked"
                                ? "bg-red-500/10 text-red-400"
                                : "bg-amber-500/10 text-amber-400"
                            }`}
                        >
                          {lic.status}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-slate-400">
                        {lic.activeInstallations} /{" "}
                        {lic.maxInstallations >= 999999
                          ? "\u221E"
                          : lic.maxInstallations}
                      </td>
                      <td className="py-3 pr-4 text-xs text-slate-500">
                        {lic.isLifetime ? "Vitalicia" : "Mensual"}
                      </td>
                      <td className="py-3 text-right">
                        {lic.status === "active" && (
                          <button
                            onClick={() => handleRevoke(lic.id)}
                            disabled={revoking === lic.id}
                            className="text-xs text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
                          >
                            {revoking === lic.id ? "..." : "Revocar"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
