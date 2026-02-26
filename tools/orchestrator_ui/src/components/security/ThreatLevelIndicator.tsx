import React from 'react';

interface ThreatLevelIndicatorProps {
    level: number;
    label: string;
    lockdown: boolean;
}

export const ThreatLevelIndicator: React.FC<ThreatLevelIndicatorProps> = ({ level, label, lockdown }) => {
    let colorClass = 'bg-accent-trust/10 text-accent-trust border-accent-trust/30';
    let icon = '🛡️';

    if (lockdown) {
        colorClass = 'bg-accent-alert/15 text-accent-alert border-accent-alert/50 animate-status-pulse';
        icon = '🔒';
    } else if (level >= 2) {
        colorClass = 'bg-accent-warning/10 text-accent-warning border-accent-warning/30 animate-status-pulse';
        icon = '⚠️';
    } else if (level === 1) {
        colorClass = 'bg-accent-warning/10 text-accent-warning border-accent-warning/30';
        icon = '👁️';
    }

    return (
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${colorClass} text-sm font-medium transition-colors duration-300`}>
            <span className="text-base">{icon}</span>
            <span>{label}</span>
            {lockdown && <span className="ml-1 text-xs opacity-80">(LOCKDOWN ACTIVE)</span>}
        </div>
    );
};
