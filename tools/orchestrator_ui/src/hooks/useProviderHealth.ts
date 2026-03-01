import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../types';

export interface ProviderHealth {
    connected: boolean;
    health: 'ok' | 'degraded' | 'error' | 'unknown';
    providerName: string;
    model: string;
    loading: boolean;
}

export function useProviderHealth(enabled: boolean = true): ProviderHealth {
    const [state, setState] = useState<ProviderHealth>({
        connected: false,
        health: 'unknown',
        providerName: '',
        model: '',
        loading: true,
    });

    const fetchHealth = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/ops/provider`, { credentials: 'include' });
            if (!res.ok) {
                setState(prev => ({ ...prev, connected: false, health: 'error', loading: false }));
                return;
            }
            const data = await res.json();
            const effective = data?.effective_state || data;
            const health = effective?.health === 'ok' ? 'ok' : (effective?.health || 'unknown');
            const connected = health === 'ok';
            const providerName = data?.display_name || data?.type || data?.provider_type || '';
            const model = data?.model || data?.model_id || '';

            setState({
                connected,
                health: health as ProviderHealth['health'],
                providerName,
                model,
                loading: false,
            });
        } catch {
            setState(prev => ({ ...prev, connected: false, health: 'error', loading: false }));
        }
    }, []);

    useEffect(() => {
        if (!enabled) return;
        fetchHealth();
        const interval = setInterval(fetchHealth, state.connected ? 30000 : 10000);
        return () => clearInterval(interval);
    }, [enabled, fetchHealth, state.connected]);

    return state;
}
