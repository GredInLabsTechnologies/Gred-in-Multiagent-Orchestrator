import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../types';

export interface ColdRoomStatus {
    enabled: boolean;
    paired: boolean;
    vm_detected?: boolean;
    machine_id?: string;
    renewal_valid?: boolean;
    renewal_needed?: boolean;
    days_remaining?: number;
    expires_at?: string;
    plan?: string;
    features?: string[];
    renewals_remaining?: number;
}

export function useColdRoomStatus(active = true) {
    const [status, setStatus] = useState<ColdRoomStatus | null>(null);
    const [loading, setLoading] = useState(false);

    const refresh = useCallback(async () => {
        if (!active) return;
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/auth/cold-room/status`, { credentials: 'include' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json() as ColdRoomStatus;
            setStatus(data);
        } catch {
            setStatus({ enabled: false, paired: false });
        } finally {
            setLoading(false);
        }
    }, [active]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    return { status, loading, refresh };
}
