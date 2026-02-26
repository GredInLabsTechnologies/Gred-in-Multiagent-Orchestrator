import React from 'react';
import { TrustRecord } from '../../hooks/useSecurityService';
import { ShieldAlert } from 'lucide-react';

interface TrustDashboardProps {
    records: TrustRecord[];
}

const getScoreBarColorClass = (score: number) => {
    if (score >= 0.9) return 'bg-accent-trust';
    if (score >= 0.7) return 'bg-accent-trust opacity-80';
    if (score >= 0.5) return 'bg-accent-warning';
    return 'bg-accent-alert';
};

const getScoreTextColorClass = (score: number) => {
    if (score >= 0.9) return 'text-accent-trust';
    if (score >= 0.7) return 'text-accent-trust';
    if (score >= 0.5) return 'text-accent-warning';
    return 'text-accent-alert';
};

const getPolicyBadgeClass = (policy: string) => {
    switch (policy) {
        case 'auto_approve': return 'bg-accent-trust/10 text-accent-trust border border-accent-trust/30';
        case 'require_review': return 'bg-accent-warning/10 text-accent-warning border border-accent-warning/30';
        case 'blocked': return 'bg-accent-alert/10 text-accent-alert border border-accent-alert/30';
        default: return 'bg-gray-500/10 text-gray-500 border-gray-500/20';
    }
};

const getPolicyLabel = (policy: string) => {
    return policy.replace('_', ' ').toUpperCase();
};

export const TrustDashboard: React.FC<TrustDashboardProps> = ({ records }) => {
    return (
        <div className="bg-surface-2 rounded-xl border border-border-subtle overflow-hidden">
            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead>
                        <tr className="border-b border-border-subtle bg-surface-0">
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Dimension</th>
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Trust Score</th>
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold text-right">Approve</th>
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold text-right">Reject</th>
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold text-right">Fail</th>
                            <th className="px-4 py-3 text-[10px] uppercase tracking-widest text-text-secondary font-semibold text-right">Policy</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                        {records.length === 0 ? (
                            <tr>
                                <td colSpan={6} className="px-4 py-8 text-center text-text-secondary text-xs">
                                    <ShieldAlert size={16} className="mx-auto mb-2 opacity-50" />
                                    No trust records found.
                                </td>
                            </tr>
                        ) : (
                            records.map((record, index) => (
                                <tr key={record.dimension_key} style={{ ['--i' as any]: index }} className="hover:bg-surface-3/50 transition-colors animate-slide-in-up">
                                    <td className="px-4 py-3 text-xs font-mono text-text-primary max-w-[150px] truncate" title={record.dimension_key}>
                                        {record.dimension_key}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-2">
                                            <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden min-w-[60px]">
                                                <div
                                                    className={`h-full rounded-full transition-all duration-500 ${getScoreBarColorClass(record.score)}`}
                                                    style={{ width: `${record.score * 100}%` }}
                                                />
                                            </div>
                                            <span className={`text-xs font-mono w-8 text-right ${getScoreTextColorClass(record.score)}`}>
                                                {Math.round(record.score * 100)}%
                                            </span>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-xs text-text-secondary text-right">{record.approvals}</td>
                                    <td className="px-4 py-3 text-xs text-text-secondary text-right">{record.rejections}</td>
                                    <td className="px-4 py-3 text-xs text-right">
                                        {record.failures > 0 ? (
                                            <span className="text-accent-alert font-medium">{record.failures}</span>
                                        ) : (
                                            <span className="text-text-secondary">-</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        <span className={`
                                            inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider
                                            ${getPolicyBadgeClass(record.policy)}
                                        `}>
                                            {getPolicyLabel(record.policy)}
                                        </span>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
