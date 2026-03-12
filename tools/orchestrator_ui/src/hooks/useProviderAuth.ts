import { useCallback } from 'react';
import { API_BASE } from '../types';

const getRequestInit = (includeJson: boolean = false): RequestInit => ({
    credentials: 'include',
    headers: {
        ...(includeJson ? { 'Content-Type': 'application/json' } : {}),
    },
});

export const useProviderAuth = () => {
    const startCodexDeviceLogin = useCallback(async () => {
        const res = await fetch(`${API_BASE}/ops/connectors/codex/login`, {
            method: 'POST',
            ...getRequestInit(true),
        });
        const data = await res.json().catch(() => ({}));
        if (data?.status === 'error') {
            const err: any = new Error(data?.message || 'Codex login error');
            if (data?.action) err.action = data.action;
            throw err;
        }
        if (!res.ok) {
            const message = data?.message || data?.detail || 'Failed to start Codex device login flow';
            const err: any = new Error(message);
            if (data?.action) err.action = data.action;
            throw err;
        }
        return data;
    }, []);

    const startClaudeLogin = useCallback(async () => {
        const res = await fetch(`${API_BASE}/ops/connectors/claude/login`, {
            method: 'POST',
            ...getRequestInit(true),
        });
        const data = await res.json().catch(() => ({}));
        if (data?.status === 'error') {
            const err: any = new Error(data?.message || 'Claude login error');
            if (data?.action) err.action = data.action;
            throw err;
        }
        if (!res.ok) {
            const message = data?.message || data?.detail || 'Failed to start Claude login flow';
            const err: any = new Error(message);
            if (data?.action) err.action = data.action;
            throw err;
        }
        return data;
    }, []);

    const fetchCliAuthStatus = useCallback(async (provider: 'codex' | 'claude') => {
        const res = await fetch(`${API_BASE}/ops/connectors/${provider}/auth-status`, getRequestInit());
        if (!res.ok) return { authenticated: false, method: null, detail: `HTTP ${res.status}` };
        return res.json().catch(() => ({ authenticated: false }));
    }, []);

    const cliLogout = useCallback(async (provider: 'codex' | 'claude') => {
        const res = await fetch(`${API_BASE}/ops/connectors/${provider}/logout`, {
            method: 'POST',
            ...getRequestInit(true),
        });
        return res.json().catch(() => ({}));
    }, []);

    return { startCodexDeviceLogin, startClaudeLogin, fetchCliAuthStatus, cliLogout };
};
