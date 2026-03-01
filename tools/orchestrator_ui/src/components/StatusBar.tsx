import React from 'react';
import { motion } from 'framer-motion';
import { Zap } from 'lucide-react';
import type { ProviderHealth } from '../hooks/useProviderHealth';

interface StatusBarProps {
    providerHealth: ProviderHealth;
    version?: string;
    serviceStatus?: string;
    onNavigateToSettings: () => void;
    onNavigateToMastery: () => void;
}

export const StatusBar: React.FC<StatusBarProps> = ({
    providerHealth,
    version,
    serviceStatus,
    onNavigateToSettings,
    onNavigateToMastery,
}) => {
    const isConnected = providerHealth.connected;
    const isDegraded = providerHealth.health === 'degraded';

    const dotColor = isConnected
        ? 'bg-emerald-400'
        : isDegraded
            ? 'bg-amber-400'
            : 'bg-red-400';

    const providerLabel = isConnected
        ? `${providerHealth.providerName || 'Provider'} · ${providerHealth.model || ''}`.trim()
        : 'Sin provider';

    return (
        <footer
            role="contentinfo"
            className="h-8 border-t border-white/[0.04] bg-surface-1/60 backdrop-blur-xl flex items-center justify-between px-4 text-[10px] text-text-tertiary shrink-0"
        >
            {/* Left: provider status */}
            <button
                onClick={onNavigateToSettings}
                className="flex items-center gap-2 hover:text-text-primary transition-colors group"
                title="Configurar provider"
                aria-label={`Provider: ${providerLabel}`}
            >
                {/* Animated health dot */}
                <span className="relative flex items-center justify-center w-3 h-3">
                    <span className={`w-2 h-2 rounded-full ${dotColor} relative z-10`} />
                    {isConnected && (
                        <motion.span
                            className={`absolute inset-0 rounded-full ${dotColor} opacity-40`}
                            animate={{ scale: [1, 1.8, 1], opacity: [0.4, 0, 0.4] }}
                            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                        />
                    )}
                    {!isConnected && !isDegraded && (
                        <motion.span
                            className="absolute inset-0 rounded-full bg-red-400 opacity-30"
                            animate={{ opacity: [0.3, 0.6, 0.3] }}
                            transition={{ duration: 1.5, repeat: Infinity }}
                        />
                    )}
                </span>

                <span className={`font-mono tracking-wide ${isConnected ? 'text-text-secondary' : 'text-red-400'} group-hover:text-text-primary transition-colors`}>
                    {providerHealth.loading ? 'verificando...' : providerLabel}
                </span>

            </button>

            {/* Center: service status */}
            <div className="flex items-center gap-1.5 font-mono text-text-tertiary">
                <Zap size={9} className={serviceStatus === 'running' ? 'text-accent-primary' : ''} />
                <span>{serviceStatus || 'idle'}</span>
            </div>

            {/* Right: version + mastery link */}
            <button
                onClick={onNavigateToMastery}
                className="flex items-center gap-2 hover:text-text-primary transition-colors font-mono"
                aria-label="Ver economía de tokens"
            >
                <span className="tracking-wider">v{version || '1.0.0'}</span>
            </button>
        </footer>
    );
};
