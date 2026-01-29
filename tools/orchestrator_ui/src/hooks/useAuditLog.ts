import { useState, useCallback, useEffect, useMemo } from 'react';
import { API_BASE } from '../types';

export const useAuditLog = (token?: string, limit: number = 200) => {
    const [logs, setLogs] = useState<string[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [filter, setFilter] = useState<'all' | 'read' | 'deny' | 'system'>('all');
    const [searchTerm, setSearchTerm] = useState('');

    const fetchLogs = useCallback(async () => {
        try {
            const headers: HeadersInit = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const res = await fetch(`${API_BASE}/ui/audit?limit=${limit}`, { headers });
            if (!res.ok) throw new Error('Failed to fetch audit logs');
            const data = await res.json();
            setLogs(data.lines || []);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
        }
    }, [token, limit]);

    useEffect(() => {
        fetchLogs();
        const interval = setInterval(fetchLogs, 5000);
        return () => clearInterval(interval);
    }, [fetchLogs]);

    const filteredLogs = useMemo(() => {
        const term = searchTerm.trim().toLowerCase();
        return logs.filter((line) => {
            const normalized = line.toLowerCase();
            if (filter === 'read' && !normalized.includes('read')) return false;
            if (filter === 'deny' && !normalized.includes('denied')) return false;
            if (filter === 'system' && normalized.includes('read')) return false;
            if (term && !normalized.includes(term)) return false;
            return true;
        }).reverse(); // Latest logs first
    }, [logs, filter, searchTerm]);

    return {
        logs: filteredLogs,
        rawLogs: logs,
        isLoading,
        error,
        filter,
        setFilter,
        searchTerm,
        setSearchTerm,
        refresh: fetchLogs
    };
};
