import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE, MeshDevice, MeshStatus, ThermalProfile } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

const POLL_INTERVAL_MS = 5000;

export const useMeshService = () => {
    const [status, setStatus] = useState<MeshStatus | null>(null);
    const [devices, setDevices] = useState<MeshDevice[]>([]);
    const [profiles, setProfiles] = useState<ThermalProfile[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const headers = { 'Content-Type': 'application/json' } as HeadersInit;
    const opts = { headers, credentials: 'include' as RequestCredentials };

    const fetchStatus = useCallback(async () => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/mesh/status`, opts);
            if (res.ok) setStatus(await res.json());
        } catch { /* ignore */ }
    }, []);

    const fetchDevices = useCallback(async () => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/mesh/devices`, opts);
            if (res.ok) setDevices(await res.json());
        } catch { /* ignore */ }
    }, []);

    const fetchProfiles = useCallback(async () => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/mesh/profiles`, opts);
            if (res.ok) setProfiles(await res.json());
        } catch { /* ignore */ }
    }, []);

    const fetchAll = useCallback(async () => {
        setIsLoading(true);
        try {
            await Promise.all([fetchStatus(), fetchDevices(), fetchProfiles()]);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch mesh data');
        } finally {
            setIsLoading(false);
        }
    }, [fetchStatus, fetchDevices, fetchProfiles]);

    const approveDevice = useCallback(async (deviceId: string) => {
        const res = await fetchWithRetry(`${API_BASE}/ops/mesh/devices/${deviceId}/approve`, {
            ...opts, method: 'POST',
        });
        if (!res.ok) throw new Error(`Failed to approve: ${res.status}`);
        await fetchDevices();
        return res.json();
    }, [fetchDevices]);

    const refuseDevice = useCallback(async (deviceId: string) => {
        const res = await fetchWithRetry(`${API_BASE}/ops/mesh/devices/${deviceId}/refuse`, {
            ...opts, method: 'POST',
        });
        if (!res.ok) throw new Error(`Failed to refuse: ${res.status}`);
        await fetchDevices();
        return res.json();
    }, [fetchDevices]);

    const removeDevice = useCallback(async (deviceId: string) => {
        const res = await fetchWithRetry(`${API_BASE}/ops/mesh/devices/${deviceId}`, {
            ...opts, method: 'DELETE',
        });
        if (!res.ok) throw new Error(`Failed to remove: ${res.status}`);
        await fetchDevices();
    }, [fetchDevices]);

    const enrollDevice = useCallback(async (data: {
        device_id: string; name?: string; device_mode?: string; device_class?: string;
    }) => {
        const res = await fetchWithRetry(`${API_BASE}/ops/mesh/enroll`, {
            ...opts, method: 'POST', body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(`Failed to enroll: ${res.status}`);
        await fetchDevices();
        return res.json();
    }, [fetchDevices]);

    // Auto-poll
    useEffect(() => {
        fetchAll();
        pollRef.current = setInterval(fetchAll, POLL_INTERVAL_MS);
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [fetchAll]);

    return {
        status, devices, profiles,
        isLoading, error,
        fetchAll, approveDevice, refuseDevice, removeDevice, enrollDevice,
    };
};
