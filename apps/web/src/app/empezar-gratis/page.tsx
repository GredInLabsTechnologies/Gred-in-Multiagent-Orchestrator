import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import { GoogleAuthButton } from "@/components/google-auth-button";

export default function EmpezarGratisPage() {
    return (
        <main className="min-h-screen bg-[#020617] text-slate-200 px-6 py-10">
            <div className="max-w-5xl mx-auto">
                <Link
                    href="/"
                    className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors mb-10"
                >
                    <ArrowLeft size={14} /> Volver al inicio
                </Link>

                <div className="grid lg:grid-cols-2 gap-8 items-stretch">
                    <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-8">
                        <p className="inline-flex items-center gap-2 text-xs font-semibold text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 px-3 py-1 rounded-full mb-6">
                            <ShieldCheck size={14} /> Acceso seguro
                        </p>

                        <h1 className="text-3xl md:text-4xl font-bold text-white mb-4">Empieza gratis con GIMO</h1>
                        <p className="text-slate-400 leading-relaxed mb-8">
                            Crea tu cuenta en segundos y entra al workspace de automatizaciones. Puedes iniciar sesión con Google.
                        </p>

                        <ul className="space-y-3 text-sm text-slate-300">
                            <li>• Sin tarjeta de crédito.</li>
                            <li>• Setup inicial en menos de 2 minutos.</li>
                            <li>• Acceso a plantillas de flujos IA desde el primer login.</li>
                        </ul>
                    </section>

                    <section className="rounded-2xl border border-slate-800 bg-[#0b1221] p-8 flex flex-col justify-center">
                        <h2 className="text-xl font-semibold text-white mb-2">Inicia sesión</h2>
                        <p className="text-sm text-slate-400 mb-6">Continúa con tu cuenta de Google:</p>

                        <GoogleAuthButton
                            className="w-full h-11 rounded-lg border border-slate-700 bg-slate-900/60 text-slate-100 hover:bg-slate-800 transition-colors inline-flex items-center justify-center gap-2 disabled:opacity-60"
                        />

                        <p className="text-xs text-slate-500 mt-6">
                            Al continuar, aceptas los términos y políticas de privacidad de GIMO.
                        </p>
                    </section>
                </div>
            </div>
        </main>
    );
}
