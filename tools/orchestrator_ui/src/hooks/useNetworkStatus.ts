import { useEffect, useState } from 'react';
import { API_BASE } from '../types';

/**
 * Tracks online/offline status via navigator.onLine + periodic /health poll.
 */
export function useNetworkStatus(pollIntervalMs = 30_000) {
    const [online, setOnline] = useState(navigator.onLine);
    const [backendReachable, setBackendReachable] = useState(true);

    useEffect(() => {
        const goOnline = () => setOnline(true);
        const goOffline = () => setOnline(false);
        window.addEventListener('online', goOnline);
        window.addEventListener('offline', goOffline);
        return () => {
            window.removeEventListener('online', goOnline);
            window.removeEventListener('offline', goOffline);
        };
    }, []);

    useEffect(() => {
        let active = true;
        const check = async () => {
            try {
                const res = await fetch(`${API_BASE}/health`, {
                    method: 'GET',
                    cache: 'no-store',
                });
                if (active) setBackendReachable(res.ok);
            } catch {
                if (active) setBackendReachable(false);
            }
        };
        check();
        const id = setInterval(check, pollIntervalMs);
        return () => { active = false; clearInterval(id); };
    }, [pollIntervalMs]);

    return { online, backendReachable, connected: online && backendReachable };
}
