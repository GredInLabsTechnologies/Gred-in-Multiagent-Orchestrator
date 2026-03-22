import { useState, useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

export const LiveLogs = () => {
    const [logs, setLogs] = useState<string[]>([]);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const response = await fetchWithRetry(`${API_BASE}/ui/audit?limit=50`, {
                    credentials: 'include'
                });
                const data = await response.json();
                if (data.lines) {
                    setLogs(data.lines);
                }
            } catch (error) {
                console.error('Error fetching logs:', error);
            }
        };

        fetchLogs();
        const interval = setInterval(fetchLogs, 3000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <div className="bg-surface-0 border border-border-primary rounded-xl overflow-hidden flex flex-col flex-1 shadow-inner">
            <div className="bg-surface-2 px-4 py-2 border-b border-border-primary flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Terminal size={14} className="text-text-secondary" />
                    <span className="text-xs font-mono text-text-secondary uppercase tracking-wider">Audit Stream (Legacy)</span>
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-accent-trust animate-pulse"></div>
                    <span className="text-[10px] text-accent-trust">LIVE</span>
                </div>
            </div>
            <div className="px-4 py-2 text-[10px] text-text-secondary border-b border-border-primary bg-surface-1">
                Vista legacy. Para filtros, búsqueda y export usa <span className="text-text-primary">Maintenance → Audit log</span>.
            </div>
            <div
                ref={scrollRef}
                className="p-4 font-mono text-xs overflow-y-auto flex-1 space-y-1"
            >
                {logs.map((log, i) => (
                    <div key={i} className="text-accent-trust opacity-80 border-l-2 border-accent-trust/20 pl-2">
                        {log}
                    </div>
                ))}
                {logs.length === 0 && (
                    <div className="text-text-secondary italic">Sin logs de auditoría activos...</div>
                )}
            </div>
        </div>
    );
};
