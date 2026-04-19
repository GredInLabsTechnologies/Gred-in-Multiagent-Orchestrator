import { API_BASE, UiStatusResponse } from '../types';
import { fetchWithRetry } from './fetchWithRetry';

type OperatorStatusSnapshot = {
    backend_status?: string;
    backend_version?: string;
    version?: string;
    uptime_seconds?: number;
    allowlist_count?: number;
    last_audit_line?: string | null;
    service_status?: string;
};

export function normalizeOperatorStatus(snapshot: OperatorStatusSnapshot): UiStatusResponse {
    return {
        version: snapshot.backend_version || snapshot.version || 'unknown',
        uptime_seconds: typeof snapshot.uptime_seconds === 'number' ? snapshot.uptime_seconds : 0,
        allowlist_count: typeof snapshot.allowlist_count === 'number' ? snapshot.allowlist_count : 0,
        last_audit_line: typeof snapshot.last_audit_line === 'string' ? snapshot.last_audit_line : null,
        service_status: typeof snapshot.service_status === 'string' && snapshot.service_status.trim()
            ? snapshot.service_status
            : 'UNKNOWN',
    };
}

export async function fetchOperatorStatus(init?: RequestInit): Promise<UiStatusResponse> {
    const response = await fetchWithRetry(`${API_BASE}/ops/operator/status`, {
        credentials: 'include',
        ...init,
    });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const snapshot = await response.json() as OperatorStatusSnapshot;
    return normalizeOperatorStatus(snapshot);
}
