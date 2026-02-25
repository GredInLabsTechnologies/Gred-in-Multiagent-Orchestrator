import React, { useState, useEffect, useCallback } from 'react';
import { Settings, Shield, Activity, Lock } from 'lucide-react';
import { TrustLevel, API_BASE } from '../types';
import { TrustBadge } from './TrustBadge';
import { useSecurityService } from '../hooks/useSecurityService';
import { ThreatLevelIndicator } from './security/ThreatLevelIndicator';
import { CircuitBreakerPanel } from './security/CircuitBreakerPanel';
import { TrustDashboard } from './security/TrustDashboard';
import { useToast } from './Toast';

interface AgentTrustEntry {
    agentId: string;
    label: string;
    trustLevel: TrustLevel;
}

interface TrustSettingsProps {
    agents?: AgentTrustEntry[];
}

const TRUST_LEVELS: { level: TrustLevel; label: string; description: string }[] = [
    { level: 'autonomous', label: 'Autonomous', description: 'Full control, no approval needed' },
    { level: 'supervised', label: 'Supervised', description: 'Actions require approval before execution' },
    { level: 'restricted', label: 'Restricted', description: 'Read-only, cannot perform actions' },
];

const DEFAULT_AGENTS: AgentTrustEntry[] = [
    { agentId: 'api', label: 'API Orchestrator', trustLevel: 'autonomous' },
    { agentId: 'tunnel', label: 'Cloudflare Tunnel', trustLevel: 'supervised' },
];

export const TrustSettings: React.FC<TrustSettingsProps> = ({ agents: initialAgents }) => {
    const { addToast } = useToast();
    const {
        threatLevel,
        threatLevelLabel,
        lockdown,
        trustDashboard,
        fetchTrustDashboard,
        getCircuitBreakerConfig,
        refresh
    } = useSecurityService();

    const [agents, setAgents] = useState<AgentTrustEntry[]>(initialAgents ?? DEFAULT_AGENTS);
    const [saving, setSaving] = useState<string | null>(null);

    useEffect(() => {
        fetchTrustDashboard();
        const interval = setInterval(fetchTrustDashboard, 10000);
        return () => clearInterval(interval);
    }, [fetchTrustDashboard]);

    const updateTrust = useCallback(async (agentId: string, newLevel: TrustLevel) => {
        setSaving(agentId);
        try {
            setAgents(prev =>
                prev.map(a => a.agentId === agentId ? { ...a, trustLevel: newLevel } : a)
            );
            addToast(`Trust level for ${agentId} set to ${newLevel}`, 'success');
        } catch (err) {
            addToast('Failed to update trust level', 'error');
        } finally {
            setSaving(null);
        }
    }, [addToast]);

    const handleInspectBreaker = async (dimensionKey: string) => {
        const config = await getCircuitBreakerConfig(dimensionKey);
        if (config) {
            addToast(
                `${dimensionKey} → window:${config.window}, threshold:${config.failure_threshold}, cooldown:${config.cooldown_seconds}s`,
                'info'
            );
        } else {
            addToast(`No custom config for ${dimensionKey} (using defaults)`, 'info');
        }
    };

    return (
        <div className="space-y-8 animate-fade-in pb-10 px-1">
            {/* Header with Threat Level */}
            <div
                className="group/threat relative flex items-center justify-between bg-[#141414] p-5 rounded-xl border border-[#1c1c1e]"
            >
                <div className="invisible group-hover/threat:visible absolute -bottom-12 left-4 right-4 z-50 p-2 rounded-lg bg-[#2c2c2e] border border-[#3c3c3e] text-[10px] text-[#86868b] shadow-xl transition-opacity">
                    Threat Level indica el riesgo global actual del sistema (NOMINAL → ALERT → GUARDED → LOCKDOWN).
                </div>
                <div className="flex items-center gap-2 text-[#f5f5f7]">
                    <Shield size={18} />
                    <span className="text-sm font-semibold">Security Status</span>
                </div>
                <div className="flex items-center gap-4">
                    <button
                        onClick={refresh}
                        className="text-xs text-[#86868b] hover:text-[#f5f5f7] transition-colors"
                    >
                        Refresh
                    </button>
                    <ThreatLevelIndicator level={threatLevel} label={threatLevelLabel} lockdown={lockdown} />
                </div>
            </div>

            {/* Circuit Breakers */}
            {trustDashboard.some(r => r.circuit_state !== 'closed' || r.failures > 0) && (
                <div className="space-y-3">
                    <div className="group/cb relative flex items-center gap-2 text-[#86868b] pl-1">
                        <div className="invisible group-hover/cb:visible absolute -bottom-10 left-0 right-0 z-50 p-2 rounded-lg bg-[#2c2c2e] border border-[#3c3c3e] text-[10px] text-[#86868b] shadow-xl">
                            Circuit breakers protegen dimensiones con fallos repetidos; se abren temporalmente para evitar daño en cascada.
                        </div>
                        <Activity size={14} />
                        <span className="text-[10px] font-bold uppercase tracking-widest">Active Circuit Breakers</span>
                    </div>
                    <CircuitBreakerPanel records={trustDashboard} onInspect={handleInspectBreaker} />
                </div>
            )}

            {/* Trust Dashboard */}
            <div className="space-y-3">
                <div className="group/td relative flex items-center gap-2 text-[#86868b] pl-1">
                    <div className="invisible group-hover/td:visible absolute -bottom-10 left-0 right-0 z-50 p-2 rounded-lg bg-[#2c2c2e] border border-[#3c3c3e] text-[10px] text-[#86868b] shadow-xl">
                        Trust Dimensions miden fiabilidad por dominio (aprobaciones, rechazos, fallos) y aplican política automática.
                    </div>
                    <Lock size={14} />
                    <span className="text-[10px] font-bold uppercase tracking-widest">Trust Dimensions</span>
                </div>
                <TrustDashboard records={trustDashboard} />
            </div>

            {/* Agent Trust Settings */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-[#86868b] pl-1 mb-2">
                    <Settings size={14} />
                    <span className="text-[10px] font-bold uppercase tracking-widest">Agent Autonomy</span>
                </div>
                <div className="space-y-3">
                    {agents.map(agent => (
                        <div
                            key={agent.agentId}
                            className="p-4 rounded-xl bg-[#141414] border border-[#1c1c1e] space-y-3"
                        >
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <span className="text-sm font-medium text-[#f5f5f7]">{agent.label}</span>
                                    <TrustBadge level={agent.trustLevel} showLabel />
                                </div>
                                <span className="text-[10px] font-mono text-[#86868b]">{agent.agentId}</span>
                            </div>

                            <div className="flex gap-2">
                                {TRUST_LEVELS.map(({ level, label, description }) => (
                                    <button
                                        key={level}
                                        onClick={() => updateTrust(agent.agentId, level)}
                                        disabled={saving === agent.agentId || agent.trustLevel === level}
                                        title={description}
                                        className={`
                                            flex-1 py-1.5 px-3 rounded-lg text-[10px] font-semibold uppercase tracking-wider
                                            border transition-all duration-200
                                                ${agent.trustLevel === level && level === 'autonomous' ? 'bg-[#32d74b]/10 border-[#32d74b]/30 text-[#32d74b]' : ''}
                                            ${agent.trustLevel === level && level === 'supervised' ? 'bg-[#ff9f0a]/10 border-[#ff9f0a]/30 text-[#ff9f0a]' : ''}
                                            ${agent.trustLevel === level && level === 'restricted' ? 'bg-[#ff453a]/10 border-[#ff453a]/30 text-[#ff453a]' : ''}
                                            ${agent.trustLevel !== level ? 'bg-[#0a0a0a] border-[#2c2c2e] text-[#86868b] hover:bg-[#1c1c1e]' : ''}
                                            disabled:opacity-50 disabled:cursor-not-allowed
                                        `}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="p-3 rounded-lg bg-[#0a0a0a] border border-[#1c1c1e] mt-4">
                <p className="text-[10px] text-[#86868b] leading-relaxed">
                    Trust levels and circuit breakers dynamically adjust based on system behavior.
                    <strong className="text-[#f5f5f7]"> Autonomous</strong> agents execute without approval unless trust score drops.
                </p>
            </div>
        </div>
    );
};
