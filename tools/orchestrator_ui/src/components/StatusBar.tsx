import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Zap, Cpu, WifiOff } from 'lucide-react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import type { ProviderHealth } from '../hooks/useProviderHealth';

interface HardwareState {
    cpu_percent: number;
    ram_percent: number;
    ram_available_gb: number;
    load_level: 'safe' | 'caution' | 'critical';
    available_models: number;
    local_models: number;
    remote_models: number;
    local_safe: boolean;
}

interface StatusBarProps {
    providerHealth: ProviderHealth;
    version?: string;
    serviceStatus?: string;
    networkConnected?: boolean;
    onNavigateToSettings: () => void;
    onNavigateToMastery: () => void;
}

export const StatusBar: React.FC<StatusBarProps> = ({
    providerHealth,
    version,
    serviceStatus,
    networkConnected = true,
    onNavigateToSettings,
    onNavigateToMastery,
}) => {
    const [hw, setHw] = useState<HardwareState | null>(null);

    useEffect(() => {
        let active = true;
        const poll = async () => {
            try {
                const res = await fetchWithRetry(`${API_BASE}/ops/mastery/hardware`, { credentials: 'include' });
                if (res.ok && active) setHw(await res.json());
            } catch (err) { console.warn('Hardware poll failed:', err); }
        };
        poll();
        const id = setInterval(poll, 15_000);
        return () => { active = false; clearInterval(id); };
    }, []);

    const isConnected = providerHealth.connected;
    const isDegraded = providerHealth.health === 'degraded';

    const hwColor = !hw ? 'text-text-tertiary'
        : hw.load_level === 'critical' ? 'text-red-400'
        : hw.load_level === 'caution' ? 'text-amber-400'
        : 'text-emerald-400';

    const dotColor = isConnected
        ? 'bg-emerald-400'
        : isDegraded
            ? 'bg-amber-400'
            : 'bg-red-400';

    const providerLabel = isConnected
        ? [providerHealth.providerName || 'Provider', providerHealth.model].filter(Boolean).join(' · ')
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

            {/* Center: hardware + service status */}
            <div className="flex items-center gap-3 font-mono text-text-tertiary">
                {hw && (
                    <span
                        className={`flex items-center gap-1 ${hwColor}`}
                        title={`CPU: ${hw.cpu_percent.toFixed(0)}% | RAM: ${hw.ram_percent.toFixed(0)}% (${hw.ram_available_gb} GB libres)\nModelos: ${hw.available_models} (${hw.local_models} local, ${hw.remote_models} remoto)\nLocal seguro: ${hw.local_safe ? 'Si' : 'No'}`}
                    >
                        <Cpu size={10} />
                        <span>{hw.cpu_percent.toFixed(0)}%</span>
                        <span className="text-text-tertiary/50">|</span>
                        <span>{hw.ram_percent.toFixed(0)}%</span>
                    </span>
                )}
                {!networkConnected && (
                    <span className="flex items-center gap-1 text-red-400" title="Backend unreachable">
                        <WifiOff size={10} />
                        <span>offline</span>
                    </span>
                )}
                <span className="flex items-center gap-1">
                    <Zap size={9} className={serviceStatus === 'running' ? 'text-accent-primary' : ''} />
                    <span>{serviceStatus || 'idle'}</span>
                </span>
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
