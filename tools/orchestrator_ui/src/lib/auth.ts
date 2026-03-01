import { API_BASE } from '../types';
import { useAppStore } from '../stores/appStore';

/**
 * Check the current session against the backend.
 * Updates appStore auth state directly.
 */
export async function checkSession(): Promise<void> {
    const store = useAppStore.getState();
    store.setBootState('checking');
    store.setBootError(null);

    try {
        const response = await fetch(`${API_BASE}/auth/check`, {
            credentials: 'include',
        });

        if (!response.ok && response.status !== 401) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json().catch(() => ({ authenticated: false }));

        if (data.authenticated === true) {
            store.login({
                email: data.email,
                displayName: data.displayName,
                plan: data.plan,
                firebaseUser: data.firebaseUser,
            });
        } else {
            store.setAuthenticated(false);
            store.setBootState('ready');
        }
    } catch {
        store.setBootError('No se pudo conectar con GIMO backend.');
        store.setBootState('offline');
    }
}

/**
 * Logout: clear server session + local state.
 */
export async function logout(): Promise<void> {
    try {
        await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include',
        });
    } catch {
        // Ignore network errors on logout
    } finally {
        useAppStore.getState().logout();
    }
}
