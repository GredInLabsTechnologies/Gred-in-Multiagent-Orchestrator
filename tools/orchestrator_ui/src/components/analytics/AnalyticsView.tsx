import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { DollarSign, Zap, AlertTriangle, TrendingUp } from 'lucide-react';
import { API_BASE } from '../../types';

interface CostAnalytics {
    daily_costs: Array<{ date: string; total: number }>;
    by_model: Array<{ model: string; cost: number; calls: number }>;
    by_task_type: Array<{ task_type: string; cost: number; calls: number }>;
    by_provider: Array<{ provider: string; cost: number; calls: number }>;
    total_savings: number;
}

interface HeroCard {
    label: string;
    value: string;
    sub?: string;
    icon: React.ReactNode;
    color: string;
}

type TabKey = 'overview' | 'models' | 'tasks' | 'providers';

export const AnalyticsView: React.FC = () => {
    const [data, setData] = useState<CostAnalytics | null>(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<TabKey>('overview');
    const [runCount, setRunCount] = useState(0);
    const [errorRate, setErrorRate] = useState(0);

    useEffect(() => {
        const fetchAnalytics = async () => {
            setLoading(true);
            try {
                const [analyticsRes, runsRes] = await Promise.all([
                    fetch(`${API_BASE}/ops/mastery/analytics`, { credentials: 'include' }),
                    fetch(`${API_BASE}/ops/runs`, { credentials: 'include' }),
                ]);

                if (analyticsRes.ok) {
                    setData(await analyticsRes.json());
                }

                if (runsRes.ok) {
                    const runs = await runsRes.json();
                    if (Array.isArray(runs)) {
                        setRunCount(runs.length);
                        const errors = runs.filter((r: any) => r.status === 'error').length;
                        setErrorRate(runs.length > 0 ? (errors / runs.length) * 100 : 0);
                    }
                }
            } catch {
                // non-blocking
            } finally {
                setLoading(false);
            }
        };

        fetchAnalytics();
    }, []);

    const totalCost = data?.daily_costs?.reduce((s, d) => s + (d.total || 0), 0) ?? 0;

    const heroCards: HeroCard[] = [
        {
            label: 'Total Cost',
            value: `$${totalCost.toFixed(4)}`,
            sub: 'accumulated USD',
            icon: <DollarSign size={18} />,
            color: 'text-emerald-400',
        },
        {
            label: 'Workflows',
            value: String(runCount),
            sub: 'total executions',
            icon: <Zap size={18} />,
            color: 'text-blue-400',
        },
        {
            label: 'Error Rate',
            value: `${errorRate.toFixed(1)}%`,
            sub: 'of failed runs',
            icon: <AlertTriangle size={18} />,
            color: errorRate > 20 ? 'text-red-400' : 'text-amber-400',
        },
        {
            label: 'Savings',
            value: `$${(data?.total_savings ?? 0).toFixed(4)}`,
            sub: 'via eco-mode + cache',
            icon: <TrendingUp size={18} />,
            color: 'text-purple-400',
        },
    ];

    const tabs: { key: TabKey; label: string }[] = [
        { key: 'overview', label: 'Resumen' },
        { key: 'models', label: 'Por Modelo' },
        { key: 'tasks', label: 'Por Tarea' },
        { key: 'providers', label: 'Por Proveedor' },
    ];

    if (loading) {
        return (
            <div className="flex-1 p-6 space-y-4">
                {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="h-20 rounded-xl bg-white/[0.03] animate-pulse" />
                ))}
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {/* Hero Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {heroCards.map((card, i) => (
                    <motion.div
                        key={card.label}
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.06 }}
                        className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4"
                    >
                        <div className="flex items-center gap-2 mb-2">
                            <span className={card.color}>{card.icon}</span>
                            <span className="text-[10px] text-white/40 uppercase tracking-wider">{card.label}</span>
                        </div>
                        <div className="text-xl font-semibold text-white/90">{card.value}</div>
                        {card.sub && <div className="text-[10px] text-white/30 mt-0.5">{card.sub}</div>}
                    </motion.div>
                ))}
            </div>

            {/* Tabs */}
            <div className="flex gap-1 bg-white/[0.03] rounded-lg p-1">
                {tabs.map((tab) => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                            activeTab === tab.key
                                ? 'bg-white/10 text-white/90'
                                : 'text-white/40 hover:text-white/60'
                        }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <AnimatePresence mode="wait">
                <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.15 }}
                >
                    {activeTab === 'overview' && (
                        <div className="space-y-3">
                            <div className="text-xs text-white/50 uppercase tracking-wider">Costos Diarios</div>
                            {data?.daily_costs && data.daily_costs.length > 0 ? (
                                <div className="flex items-end gap-1 h-32 px-2">
                                    {data.daily_costs.slice(-14).map((d, i) => {
                                        const maxCost = Math.max(...data.daily_costs.map((c) => c.total || 0.001));
                                        const height = Math.max(4, (d.total / maxCost) * 100);
                                        return (
                                            <div key={i} className="flex-1 flex flex-col items-center gap-1">
                                                <div
                                                    className="w-full rounded-t bg-accent-primary/40 hover:bg-accent-primary/60 transition-colors"
                                                    style={{ height: `${height}%` }}
                                                    title={`${d.date}: $${d.total.toFixed(4)}`}
                                                />
                                                <span className="text-[8px] text-white/20">{d.date?.slice(-2)}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="text-sm text-white/30 py-8 text-center">No cost data</div>
                            )}
                        </div>
                    )}

                    {activeTab === 'models' && (
                        <TableView
                            items={data?.by_model || []}
                            columns={[
                                { key: 'model', label: 'Modelo' },
                                { key: 'calls', label: 'Calls' },
                                { key: 'cost', label: 'Costo', format: (v) => `$${Number(v).toFixed(4)}` },
                            ]}
                        />
                    )}

                    {activeTab === 'tasks' && (
                        <TableView
                            items={data?.by_task_type || []}
                            columns={[
                                { key: 'task_type', label: 'Tipo' },
                                { key: 'calls', label: 'Calls' },
                                { key: 'cost', label: 'Costo', format: (v) => `$${Number(v).toFixed(4)}` },
                            ]}
                        />
                    )}

                    {activeTab === 'providers' && (
                        <TableView
                            items={data?.by_provider || []}
                            columns={[
                                { key: 'provider', label: 'Proveedor' },
                                { key: 'calls', label: 'Calls' },
                                { key: 'cost', label: 'Costo', format: (v) => `$${Number(v).toFixed(4)}` },
                            ]}
                        />
                    )}
                </motion.div>
            </AnimatePresence>
        </div>
    );
};

/* ── Generic table ── */

interface Column {
    key: string;
    label: string;
    format?: (v: any) => string;
}

function TableView({ items, columns }: { items: any[]; columns: Column[] }) {
    if (!items.length) {
        return <div className="text-sm text-white/30 py-8 text-center">No data</div>;
    }

    return (
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
            <table className="w-full text-xs">
                <thead>
                    <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                        {columns.map((col) => (
                            <th key={col.key} className="text-left px-3 py-2 text-white/40 uppercase tracking-wider font-normal">
                                {col.label}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {items.map((item, i) => (
                        <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                            {columns.map((col) => (
                                <td key={col.key} className="px-3 py-2 text-white/70">
                                    {col.format ? col.format(item[col.key]) : String(item[col.key] ?? '')}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
