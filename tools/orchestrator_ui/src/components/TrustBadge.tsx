import React from 'react';
import { ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import { TrustLevel } from '../types';

interface TrustBadgeProps {
    level: TrustLevel;
    size?: number;
    showLabel?: boolean;
}

export const TrustBadge: React.FC<TrustBadgeProps> = ({ level, size = 12, showLabel = false }) => {
    const config = {
        autonomous: {
            icon: ShieldCheck,
            color: 'text-accent-trust',
            bg: 'bg-accent-trust/10',
            border: 'border-accent-trust/30',
            label: 'Autonomous'
        },
        supervised: {
            icon: ShieldQuestion,
            color: 'text-accent-warning',
            bg: 'bg-accent-warning/10',
            border: 'border-accent-warning/30',
            label: 'Supervised'
        },
        restricted: {
            icon: ShieldAlert,
            color: 'text-accent-alert',
            bg: 'bg-accent-alert/10',
            border: 'border-accent-alert/30',
            label: 'Restricted'
        }
    };

    const { icon: Icon, color, bg, border, label } = config[level] || config.supervised;

    return (
        <div className={`
            inline-flex items-center gap-1.5 px-2 py-1 rounded-full border 
            ${bg} ${border} ${color} transition-all duration-300
        `}>
            <Icon size={size} />
            {showLabel && (
                <span className="text-[9px] font-bold uppercase tracking-wider">
                    {label}
                </span>
            )}
        </div>
    );
};
