import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { signInWithPopup } from 'firebase/auth';
import { API_BASE } from '../types';
import { auth, googleProvider, isFirebaseConfigured } from '../lib/firebase';
import { useToast } from './Toast';
import { AuthGraphBackground } from './AuthGraphBackground';
import { useColdRoomStatus } from '../hooks/useColdRoomStatus';
import { LoginBootSequence } from './login/LoginBootSequence';
import { LoginGlassCard } from './login/LoginGlassCard';
import { AuthMethodSelector, type AuthMethod } from './login/AuthMethodSelector';
import { GoogleSSOPanel } from './login/GoogleSSOPanel';
import { TokenLoginPanel } from './login/TokenLoginPanel';
import { ColdRoomActivatePanel } from './login/ColdRoomActivatePanel';
import { ColdRoomRenewalPanel } from './login/ColdRoomRenewalPanel';
import { AuthLoadingOverlay } from './login/AuthLoadingOverlay';
import { AuthSuccessTransition } from './login/AuthSuccessTransition';
import { AuthErrorPanel } from './login/AuthErrorPanel';
import { LoginParallaxLayer } from './login/LoginParallaxLayer';

interface Props {
    onAuthenticated: () => void;
}

export function LoginModal({ onAuthenticated }: Props) {
    const { addToast } = useToast();
    const { status: coldStatus, loading: coldRoomLoading, refresh: refreshColdStatus } = useColdRoomStatus(true);

    const [loginState, setLoginState] = useState<'boot' | 'select' | 'google' | 'token' | 'cold-activate' | 'cold-renew' | 'verifying' | 'success'>('boot');
    const [token, setToken] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [googleLoading, setGoogleLoading] = useState(false);
    const [loading, setLoading] = useState(false);
    const [verifyingContext, setVerifyingContext] = useState<'google' | 'token' | 'cold-activate' | 'cold-renew' | 'cold-access' | null>(null);
    const [mouseX, setMouseX] = useState(0);
    const [mouseY, setMouseY] = useState(0);
    const [reducedMotion, setReducedMotion] = useState(false);
    const [cardReady, setCardReady] = useState(false);

    const cardParallaxStyle = reducedMotion
        ? undefined
        : {
            transform: `translate(${mouseX * -0.005}px, ${mouseY * -0.005}px)`,
        };

    const visualState: 'idle' | 'verifying' | 'success' | 'error' = loginState === 'verifying'
        ? 'verifying'
        : loginState === 'success'
            ? 'success'
            : error
                ? 'error'
                : 'idle';

    const readErrorDetail = async (res: Response, fallback: string) => {
        const data = await res.json().catch(() => ({ detail: fallback }));
        return String(data?.detail || fallback);
    };

    const toColdRoomErrorMessage = (detail: string) => {
        const normalized = detail.toLowerCase();
        if (normalized.includes('invalid_signature')) return 'Firma inválida: el blob no fue emitido por una autoridad válida.';
        if (normalized.includes('machine_mismatch')) return 'Machine ID no coincide con esta instalación.';
        if (normalized.includes('expired')) return 'La licencia está expirada. Solicita un nuevo blob de renovación.';
        if (normalized.includes('unsupported_license_version')) return 'Versión de licencia no soportada. Solicita una licencia v2.';
        if (normalized.includes('nonce_replay')) return 'Este blob ya fue utilizado. Solicita uno nuevo al portal de licencias.';
        if (normalized.includes('cold_room_not_paired')) return 'Esta instalación no está emparejada en Cold Room. Activa una licencia primero.';
        if (normalized.includes('cold_room_renewal_required')) return 'La licencia Cold Room requiere renovación para continuar.';
        return detail;
    };

    const verifyingLabel = (() => {
        if (verifyingContext === 'google') return 'Verificando sesión con Google...';
        if (verifyingContext === 'token') return 'Validando token local...';
        if (verifyingContext === 'cold-activate') return 'Validando firma y activando licencia Cold Room...';
        if (verifyingContext === 'cold-renew') return 'Validando blob de renovación Cold Room...';
        if (verifyingContext === 'cold-access') return 'Validando acceso de licencia Cold Room activa...';
        return 'Verificando credenciales...';
    })();

    useEffect(() => {
        const media = window.matchMedia('(prefers-reduced-motion: reduce)');
        setReducedMotion(media.matches);
        const handle = () => setReducedMotion(media.matches);
        media.addEventListener('change', handle);
        return () => media.removeEventListener('change', handle);
    }, []);

    useEffect(() => {
        if (reducedMotion) {
            setLoginState('select');
            setCardReady(true);
            return;
        }
        const t = window.setTimeout(() => setLoginState('select'), 300);
        return () => window.clearTimeout(t);
    }, [reducedMotion]);

    useEffect(() => {
        if (loginState === 'boot') {
            setCardReady(false);
            return;
        }
        const t = window.setTimeout(() => setCardReady(true), 80);
        return () => window.clearTimeout(t);
    }, [loginState]);

    const renewalNeeded = useMemo(
        () => Boolean(coldStatus?.enabled && coldStatus?.paired && (coldStatus?.renewal_needed || coldStatus?.renewal_valid === false)),
        [coldStatus],
    );

    const goSelect = () => {
        setError(null);
        setVerifyingContext(null);
        setLoginState('select');
    };

    const handleMethodSelect = async (method: AuthMethod) => {
        setError(null);
        setVerifyingContext(null);
        if (method === 'cold-access') {
            await handleColdAccess();
            return;
        }
        setLoginState(method);
    };

    const handleColdAccess = async () => {
        setLoading(true);
        setError(null);
        setVerifyingContext('cold-access');
        setLoginState('verifying');
        try {
            const response = await fetch(`${API_BASE}/auth/cold-room/access`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) {
                setLoginState('select');
                const detail = await readErrorDetail(response, 'No se pudo validar la licencia Cold Room activa.');
                setError(toColdRoomErrorMessage(detail));
                return;
            }
            addToast('Acceso Cold Room validado', 'success');
            setLoginState('success');
            window.setTimeout(() => onAuthenticated(), 450);
        } catch {
            setLoginState('select');
            setError('No se pudo validar acceso Cold Room. Revisa estado de licencia e inténtalo de nuevo.');
        } finally {
            setLoading(false);
        }
    };

    const handleGoogleLogin = async () => {
        if (!isFirebaseConfigured() || !auth || !googleProvider) {
            setError('Firebase no está configurado. Revisa variables VITE_FIREBASE_*');
            return;
        }

        setError(null);
        setVerifyingContext('google');
        setLoginState('verifying');
        setGoogleLoading(true);

        try {
            const credentials = await signInWithPopup(auth, googleProvider);
            const idToken = await credentials.user.getIdToken();

            const res = await fetch(`${API_BASE}/auth/firebase-login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ idToken }),
            });

            if (!res.ok) {
                setLoginState('google');
                setError(await readErrorDetail(res, `HTTP ${res.status}`));
                return;
            }

            addToast('Sesión iniciada con Google', 'success');
            setLoginState('success');
            window.setTimeout(() => onAuthenticated(), 450);
        } catch {
            setLoginState('google');
            setError('No se pudo iniciar sesión con Google');
        } finally {
            setGoogleLoading(false);
        }
    };

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setError(null);
        setVerifyingContext('token');
        setLoginState('verifying');
        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ token: token.trim() }),
            });

            if (!res.ok) {
                setLoginState('token');
                setError(await readErrorDetail(res, `HTTP ${res.status}`));
                return;
            }

            setLoginState('success');
            window.setTimeout(() => onAuthenticated(), 450);
        } catch {
            setLoginState('token');
            setError('No se puede conectar al servidor');
        } finally {
            setLoading(false);
        }
    };

    const createColdRoomSession = async (): Promise<boolean> => {
        const res = await fetch(`${API_BASE}/auth/cold-room/access`, {
            method: 'POST',
            credentials: 'include',
        });
        return res.ok;
    };

    const handleColdActivate = async (licenseBlob: string) => {
        setLoading(true);
        setError(null);
        setVerifyingContext('cold-activate');
        setLoginState('verifying');
        try {
            const response = await fetch(`${API_BASE}/auth/cold-room/activate`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_blob: licenseBlob }),
            });
            if (!response.ok) {
                setLoginState('cold-activate');
                const detail = await readErrorDetail(response, 'No se pudo activar la licencia Cold Room.');
                setError(toColdRoomErrorMessage(detail));
                return;
            }
            await refreshColdStatus();
            const sessionOk = await createColdRoomSession();
            if (!sessionOk) {
                setLoginState('cold-activate');
                setError('Licencia activada pero no se pudo crear la sesión. Intenta de nuevo.');
                return;
            }
            addToast('Licencia Cold Room activada', 'success');
            setLoginState('success');
            window.setTimeout(() => onAuthenticated(), 450);
        } catch {
            setLoginState('cold-activate');
            setError('No se pudo activar la licencia de Cold Room. Revisa el blob e inténtalo de nuevo.');
        } finally {
            setLoading(false);
        }
    };

    const handleColdRenew = async (licenseBlob: string) => {
        setLoading(true);
        setError(null);
        setVerifyingContext('cold-renew');
        setLoginState('verifying');
        try {
            const response = await fetch(`${API_BASE}/auth/cold-room/renew`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_blob: licenseBlob }),
            });
            if (!response.ok) {
                setLoginState('cold-renew');
                const detail = await readErrorDetail(response, 'No se pudo renovar la licencia Cold Room.');
                setError(toColdRoomErrorMessage(detail));
                return;
            }
            await refreshColdStatus();
            const sessionOk = await createColdRoomSession();
            if (!sessionOk) {
                setLoginState('cold-renew');
                setError('Licencia renovada pero no se pudo crear la sesión. Intenta de nuevo.');
                return;
            }
            addToast('Renovación Cold Room aplicada', 'success');
            setLoginState('success');
            window.setTimeout(() => onAuthenticated(), 450);
        } catch {
            setLoginState('cold-renew');
            setError('Blob de renovación inválido. Revisa firma/máquina/expiración.');
        } finally {
            setLoading(false);
        }
    };

    const renderedPanel =
        loginState === 'select' ? (
            <AuthMethodSelector
                canUseColdRoom={Boolean(coldStatus?.enabled)}
                paired={Boolean(coldStatus?.paired)}
                renewalNeeded={renewalNeeded}
                vmDetected={Boolean(coldStatus?.vm_detected)}
                coldRoomLoading={coldRoomLoading}
                onSelect={(method) => void handleMethodSelect(method)}
            />
        ) : loginState === 'google' ? (
            <GoogleSSOPanel loading={googleLoading} onLogin={() => void handleGoogleLogin()} />
        ) : loginState === 'token' ? (
            <TokenLoginPanel
                token={token}
                loading={loading}
                onTokenChange={setToken}
                onSubmit={(e) => void handleSubmit(e)}
            />
        ) : loginState === 'cold-activate' ? (
            <ColdRoomActivatePanel
                machineId={coldStatus?.machine_id}
                loading={loading}
                onActivate={handleColdActivate}
            />
        ) : loginState === 'cold-renew' ? (
            <ColdRoomRenewalPanel
                expiresAt={coldStatus?.expires_at}
                daysRemaining={coldStatus?.days_remaining}
                plan={coldStatus?.plan}
                features={coldStatus?.features}
                renewalsRemaining={coldStatus?.renewals_remaining}
                loading={loading}
                onRenew={handleColdRenew}
            />
        ) : null;

    return (
        <div
            className="relative min-h-screen overflow-hidden bg-surface-0 flex items-center justify-center p-6"
            onMouseMove={(e) => {
                setMouseX(e.clientX - window.innerWidth / 2);
                setMouseY(e.clientY - window.innerHeight / 2);
            }}
        >
            <AuthGraphBackground loginState={visualState} />
            <LoginParallaxLayer mouseX={mouseX} mouseY={mouseY} reducedMotion={reducedMotion} visualState={visualState} />

            <LoginBootSequence done={loginState !== 'boot'} />

            <AuthLoadingOverlay visible={loginState === 'verifying'} label={verifyingLabel} />
            <AuthSuccessTransition visible={loginState === 'success'} />

            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,var(--glow-primary),transparent_42%),radial-gradient(circle_at_80%_80%,var(--glow-trust),transparent_38%),linear-gradient(180deg,color-mix(in_srgb,var(--surface-0)_45%,transparent),color-mix(in_srgb,var(--surface-0)_85%,transparent))]" />

            <div className={`transition-all duration-500 ${cardReady ? 'opacity-100 translate-y-0 scale-100' : 'opacity-0 translate-y-4 scale-[0.985]'}`}>
                <LoginGlassCard visualState={visualState} style={cardParallaxStyle}>
                    <div className="text-center space-y-1">
                        <h1 className="text-xl font-semibold text-text-primary">GIMO</h1>
                        <p className="text-sm text-text-secondary">Precision Login Interface</p>
                    </div>

                    {renderedPanel && (
                        <div key={loginState} className="animate-slide-in-up">
                            {renderedPanel}
                        </div>
                    )}

                    {error && <AuthErrorPanel error={error} onRetry={goSelect} />}

                    {loginState !== 'select' && loginState !== 'boot' && loginState !== 'verifying' && loginState !== 'success' && (
                        <button onClick={goSelect} className="text-xs text-text-secondary hover:text-text-primary underline underline-offset-2">
                            Cambiar método de acceso
                        </button>
                    )}
                </LoginGlassCard>
            </div>
        </div>
    );
}
