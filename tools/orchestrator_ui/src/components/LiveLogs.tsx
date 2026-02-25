import { useState, useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';
import { API_BASE } from '../types';

export const LiveLogs = () => {
    const [logs, setLogs] = useState<string[]>([]);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const response = await fetch(`${API_BASE}/ui/audit?limit=50`, {
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
        <div className="bg-[#000000] border border-[#38383a] rounded-xl overflow-hidden flex flex-col flex-1 shadow-inner">
            <div className="bg-[#1c1c1e] px-4 py-2 border-b border-[#38383a] flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Terminal size={14} className="text-[#86868b]" />
                    <span className="text-xs font-mono text-[#86868b] uppercase tracking-wider">Audit Stream (Legacy)</span>
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-[#32d74b] animate-pulse"></div>
                    <span className="text-[10px] text-[#32d74b]">LIVE</span>
                </div>
            </div>
            <div className="px-4 py-2 text-[10px] text-[#86868b] border-b border-[#38383a] bg-[#0a0a0a]">
                Vista legacy. Para filtros, búsqueda y export usa <span className="text-[#f5f5f7]">Maintenance → Audit log</span>.
            </div>
            <div
                ref={scrollRef}
                className="p-4 font-mono text-xs overflow-y-auto flex-1 space-y-1"
            >
                {logs.map((log, i) => (
                    <div key={i} className="text-[#32d74b] opacity-80 border-l-2 border-[#32d74b] border-opacity-20 pl-2">
                        {log}
                    </div>
                ))}
                {logs.length === 0 && (
                    <div className="text-[#86868b] italic">Sin logs de auditoría activos...</div>
                )}
            </div>
        </div>
    );
};
