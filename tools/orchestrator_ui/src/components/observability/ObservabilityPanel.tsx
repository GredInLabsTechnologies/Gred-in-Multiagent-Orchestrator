import React, { useEffect, useState } from 'react';
import { useObservabilityService } from '../../hooks/useObservabilityService';
import { ObservabilityMetrics } from '../../types';
import { Activity, BarChart2, Coins, AlertOctagon, Shuffle } from 'lucide-react';
import { TraceViewer } from './TraceViewer';

export const ObservabilityPanel: React.FC = () => {
    const { getMetrics } = useObservabilityService();
    const [metrics, setMetrics] = useState<ObservabilityMetrics | null>(null);

    useEffect(() => {
        const fetchMetrics = async () => {
            const data = await getMetrics();
            setMetrics(data);
        };
        fetchMetrics();
        const interval = setInterval(fetchMetrics, 5000); // Poll every 5s
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="flex flex-col h-full bg-surface-0 text-text-primary p-6 space-y-6">
            <div className="flex justify-between items-center">
                <h1 className="text-xl font-bold tracking-tight">Metrics Dashboard</h1>
                <div className="flex items-center gap-2 text-xs text-text-secondary">
                    <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                    <span>Live Monitoring</span>
                </div>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-6 gap-4">
                <MetricCard
                    label="Total Workflows"
                    value={metrics?.total_workflows ?? 0}
                    icon={Activity}
                />
                <MetricCard
                    label="Active Workflows"
                    value={metrics?.active_workflows ?? 0}
                    icon={BarChart2}
                    color="text-blue-500"
                />
                <MetricCard
                    label="Est. Cost"
                    value={`$${metrics?.estimated_cost?.toFixed(4) ?? '0.0000'}`}
                    icon={Coins}
                    color="text-yellow-500"
                />
                <MetricCard
                    label="Error Rate"
                    value={`${((metrics?.error_rate ?? 0) * 100).toFixed(1)}%`}
                    icon={AlertOctagon}
                    color={metrics && metrics.error_rate > 0.05 ? "text-red-500" : "text-green-500"}
                />
                <MetricCard
                    label="Avg Latency"
                    value={`${Math.round(metrics?.avg_latency_ms ?? 0)} ms`}
                    icon={Activity}
                    color="text-accent-primary"
                />
                <MetricCard
                    label="Fallback Rate"
                    value={`${((metrics?.fallback_rate ?? 0) * 100).toFixed(1)}%`}
                    icon={Shuffle}
                    color="text-violet-400"
                />
            </div>

            {/* Trace Viewer Section */}
            <div className="flex-1 min-h-0 flex flex-col pt-4">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-bold uppercase tracking-widest text-text-secondary">Trace Explorer</h2>
                </div>
                <div className="flex-1 min-h-0">
                    <TraceViewer />
                </div>
            </div>
        </div>
    );
};

const MetricCard: React.FC<{
    label: string;
    value: string | number;
    icon: React.ElementType;
    change?: string;
    color?: string
}> = ({ label, value, icon: Icon, change, color = "text-text-primary" }) => (
    <div className="bg-surface-1 border border-border-primary p-4 rounded-xl flex flex-col justify-between h-24">
        <div className="flex justify-between items-start">
            <span className="text-[10px] uppercase font-bold text-text-secondary tracking-wider">{label}</span>
            <Icon size={14} className="text-text-secondary" />
        </div>
        <div className="flex items-end justify-between">
            <span className={`text-2xl font-mono font-medium ${color}`}>{value}</span>
            {change && (
                <span className="text-[10px] text-green-500 font-medium bg-green-500/10 px-1.5 py-0.5 rounded">
                    {change}
                </span>
            )}
        </div>
    </div>
);
