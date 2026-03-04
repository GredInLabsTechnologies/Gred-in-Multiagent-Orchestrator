"use client";

import { useEffect, useState } from "react";
import { Chrome } from "lucide-react";
import {
    GoogleAuthProvider,
    onAuthStateChanged,
    signInWithPopup,
    signInWithRedirect,
    getRedirectResult,
    AuthError,
} from "firebase/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { auth } from "@/lib/firebase";

type GoogleAuthButtonProps = {
    signedInLabel?: string;
    className?: string;
};

export function GoogleAuthButton({ signedInLabel = "Conectado", className = "" }: GoogleAuthButtonProps) {
    const [userName, setUserName] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const router = useRouter();

    useEffect(() => {
        if (!auth) return;

        // Procesar resultado de redirect si viene de uno
        setLoading(true);
        getRedirectResult(auth)
            .then((result) => {
                if (result?.user) {
                    setUserName(result.user.displayName || result.user.email || "Usuario");
                    router.push("/account");
                }
            })
            .catch((error: AuthError) => {
                console.error("Error en redirect result:", error.code, error.message);
                // Mostrar error real si no es una operación cancelada
                if (error.code !== "auth/redirect-cancelled-by-user") {
                    alert(`Error al recuperar sesión: ${error.message} (${error.code})`);
                }
            })
            .finally(() => setLoading(false));

        return onAuthStateChanged(auth, (user) => {
            setUserName(user?.displayName || user?.email || null);
        });
    }, [router]);

    const handleSignIn = async () => {
        if (!auth) {
            alert("Falta configuración de Firebase. Revisa las variables NEXT_PUBLIC_FIREBASE_*");
            return;
        }

        const provider = new GoogleAuthProvider();
        provider.addScope("email");
        provider.addScope("profile");

        try {
            setLoading(true);
            // Primero intentamos popup (más rápido)
            const result = await signInWithPopup(auth, provider);
            setUserName(result.user.displayName || result.user.email || "Usuario");
            router.push("/account");
        } catch (popupError: unknown) {
            const error = popupError as AuthError;
            console.warn("Popup falló, intentando redirect:", error.code, error.message);

            // Si el popup falla por dominio no autorizado o bloqueado por el navegador → redirect
            const redirectFallbackCodes = [
                "auth/unauthorized-domain",
                "auth/popup-blocked",
            ];

            // Si el usuario cerró el popup intencionalmente, no hacemos nada
            const userCancelledCodes = [
                "auth/popup-closed-by-user",
                "auth/cancelled-popup-request",
            ];

            if (userCancelledCodes.includes(error.code)) {
                // El usuario cerró el popup — no mostrar error
                setLoading(false);
            } else if (redirectFallbackCodes.includes(error.code)) {
                try {
                    await signInWithRedirect(auth, provider);
                    // La página se recargará; getRedirectResult() en el useEffect se encarga del resultado
                } catch (redirectError: unknown) {
                    const rErr = redirectError as AuthError;
                    console.error("Error en redirect:", rErr.code, rErr.message);
                    alert(`Error al iniciar sesión: ${rErr.message} (${rErr.code})`);
                    setLoading(false);
                }
            } else {
                console.error("Error en popup:", error.code, error.message);
                alert(`Error al iniciar sesión: ${error.message}\n\nCódigo: ${error.code}`);
                setLoading(false);
            }
        }
    };


    if (userName) {
        return (
            <Link
                href="/account"
                className={`text-sm font-medium text-emerald-300 hover:text-white transition-all inline-flex items-center gap-2 group ${className}`}
            >
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="group-hover:underline underline-offset-4">
                    {signedInLabel}: {userName}
                </span>
            </Link>
        );
    }

    return (
        <button
            type="button"
            onClick={handleSignIn}
            disabled={loading}
            className={`text-sm font-medium text-slate-300 hover:text-white transition-colors inline-flex items-center gap-2 disabled:opacity-60 ${className}`}
        >
            <Chrome size={14} />
            {loading ? "Conectando..." : "Entrar con Google"}
        </button>
    );
}
