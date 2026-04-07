import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

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

export interface TrustRecord {
    dimension_key: string;
    approvals: number;
    rejections: number;
    failures: number;
    auto_approvals: number;
    streak: number;
    score: number;
    policy: 'auto_approve' | 'require_review' | 'blocked';
    circuit_state: 'closed' | 'open' | 'half_open';
    circuit_opened_at: string | null;
    last_updated: string | null;
}

export interface CircuitBreakerConfig {
    window: number;
    failure_threshold: number;
    recovery_probes: number;
    cooldown_seconds: number;
}

export const useSecurityService = (_token?: string) => {
    const [status, setStatus] = useState<SecurityStatus | null>(null);
    const [trustDashboard, setTrustDashboard] = useState<TrustRecord[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const getRequestInit = (): RequestInit => ({
        credentials: 'include',
        headers: undefined,
    });

    const fetchStatus = useCallback(async () => {
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/security/events`, getRequestInit());

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
            } else {
                setError('Failed to fetch security status');
            }
        } catch (err) {
            console.error('Failed to fetch security status:', err);
            setError(err instanceof Error ? err.message : 'Network error');
        }
    }, []);

    const fetchTrustDashboard = useCallback(async (limit: number = 100) => {
        setIsLoading(true);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/trust/dashboard?limit=${limit}`, getRequestInit());

            if (response.ok) {
                const data = await response.json();
                // R17 Cluster E.1: backend envelope canonicalized to ``entries``;
                // ``items`` retained as a legacy alias.
                setTrustDashboard(data.entries || data.items || []);
            } else {
                console.error('Failed to fetch trust dashboard');
            }
        } catch (err) {
            console.error('Network error fetching trust dashboard:', err);
        } finally {
            setIsLoading(false);
        }
    }, []);

    const getCircuitBreakerConfig = async (dimensionKey: string): Promise<CircuitBreakerConfig | null> => {
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/trust/circuit-breaker/${encodeURIComponent(dimensionKey)}`, getRequestInit());
            if (response.ok) {
                return await response.json();
            }
            return null;
        } catch (err) {
            console.error(`Failed to fetch circuit breaker config for ${dimensionKey}:`, err);
            return null;
        }
    };

    const resolveSecurity = async (action: 'clear_all' | 'downgrade' = 'clear_all') => {
        setIsLoading(true);
        try {
            const endpoint = action === 'clear_all' ? '/ops/trust/reset' : `/ops/security/resolve?action=${action}`;
            const method = 'POST';

            const response = await fetchWithRetry(`${API_BASE}${endpoint}`, {
                method,
                ...getRequestInit(),
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
        // Status
        threatLevel: status?.threatLevel ?? 0,
        threatLevelLabel: status?.threatLevelLabel ?? 'NOMINAL',
        autoDecayRemaining: status?.autoDecayRemaining,
        activeSources: status?.activeSources ?? 0,
        lockdown: (status?.threatLevel ?? 0) >= 3,

        // Data
        trustDashboard,

        // State
        isLoading,
        error,

        // Actions
        clearLockdown: () => resolveSecurity('clear_all'),
        resetThreats: () => resolveSecurity('clear_all'),
        downgrade: () => resolveSecurity('downgrade'),
        refresh: fetchStatus,
        fetchTrustDashboard,
        getCircuitBreakerConfig
    };
};
