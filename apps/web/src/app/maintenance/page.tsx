import { Wrench } from "lucide-react";

export const metadata = {
    title: "GIMO — En mantenimiento",
    description: "Estamos realizando tareas de mantenimiento. Volvemos pronto.",
};

export default function MaintenancePage() {
    return (
        <main className="min-h-screen bg-[#020617] text-slate-200 flex items-center justify-center px-6">
            <div className="max-w-md w-full text-center space-y-6">
                {/* Icono */}
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 mx-auto">
                    <Wrench size={28} className="text-indigo-400" />
                </div>

                {/* Logo */}
                <p className="text-xs font-bold tracking-widest text-indigo-400 uppercase">GIMO</p>

                {/* Título */}
                <h1 className="text-3xl font-bold text-white">Volvemos pronto</h1>

                {/* Descripción */}
                <p className="text-slate-400 leading-relaxed">
                    Estamos realizando tareas de mantenimiento para mejorar tu experiencia.
                    Estaremos de vuelta en breve.
                </p>

                {/* Separador */}
                <div className="border-t border-slate-800 my-2" />

                {/* Status badge */}
                <div className="inline-flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-4 py-2 rounded-full">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                    Mantenimiento en progreso
                </div>
            </div>
        </main>
    );
}
