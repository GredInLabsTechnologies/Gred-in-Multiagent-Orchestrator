import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../types';

export interface SecurityEvent {
    timestamp: number;
    type: string;
    severity: string;
    source: string;
    detail: string;
    resolved: boolean;
}

export interface SecurityStatus {
    threatLevel: number;
    threatLevelLabel: string;
    autoDecayRemaining: number | null;
    activeSources: number;
    panicMode: boolean; // backward compat
    recentEventsCount: number;
}

export const useSecurityService = (token?: string) => {
    const [status, setStatus] = useState<SecurityStatus | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchStatus = useCallback(async () => {
        if (!token) return;
        try {
            const response = await fetch(`${API_BASE}/ui/security/events`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const data = await response.json();
                setStatus({
                    threatLevel: data.threat_level,
                    threatLevelLabel: data.threat_level_label,
                    autoDecayRemaining: data.auto_decay_remaining,
                    activeSources: data.active_sources,
                    panicMode: data.panic_mode,
                    recentEventsCount: data.recent_events_count
                });
                setError(null);
            } else if (response.status === 503) {
                // Lockdown detected via 503
                setStatus(prev => prev ? { ...prev, threatLevel: 3, threatLevelLabel: 'LOCKDOWN', panicMode: true } : null);
            }
        } catch (err) {
            console.error('Failed to fetch security status:', err);
        }
    }, [token]);

    const resolveSecurity = async (action: 'clear_all' | 'downgrade' = 'clear_all') => {
        if (!token) return;
        setIsLoading(true);
        try {
            const response = await fetch(`${API_BASE}/ui/security/resolve?action=${action}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                await fetchStatus();
            } else {
                const data = await response.json().catch(() => ({}));
                setError(data.detail || `Failed to ${action} security`);
            }
        } catch (err) {
            setError(`Network error while resolving security: ${err}`);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 10000);
        return () => clearInterval(interval);
    }, [fetchStatus]);

    // Handle real-time updates from other requests via X-Threat-Level header
    useEffect(() => {
        const handleThreatHeader = (e: CustomEvent<{ level: string }>) => {
            if (e.detail.level !== status?.threatLevelLabel) {
                fetchStatus();
            }
        };
        window.addEventListener('threat-level-updated' as any, handleThreatHeader as any);
        return () => window.removeEventListener('threat-level-updated' as any, handleThreatHeader as any);
    }, [status, fetchStatus]);

    return {
        threatLevel: status?.threatLevel ?? 0,
        threatLevelLabel: status?.threatLevelLabel ?? 'NOMINAL',
        autoDecayRemaining: status?.autoDecayRemaining,
        activeSources: status?.activeSources ?? 0,
        lockdown: (status?.threatLevel ?? 0) >= 3,
        isLoading,
        error,
        clearLockdown: () => resolveSecurity('clear_all'),
        downgrade: () => resolveSecurity('downgrade'),
        refresh: fetchStatus
    };
};
