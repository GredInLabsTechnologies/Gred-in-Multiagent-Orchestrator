import React from 'react';
import { AlertTriangle, CheckCircle, Info } from 'lucide-react';
import { QualityMetrics, DegradationFlag } from '../types';

interface QualityAlertPanelProps {
    quality?: QualityMetrics;
}

export const QualityAlertPanel: React.FC<QualityAlertPanelProps> = ({ quality }) => {
    if (!quality) {
        return (
            <div className="p-8 text-center">
                <Info size={32} className="mx-auto text-[#2c2c2e] mb-3" />
                <div className="text-sm text-[#86868b]">Sin métricas de calidad disponibles para este nodo.</div>
            </div>
        );
    }

    const { score, alerts, lastCheck } = quality;

    const getAlertLabel = (flag: DegradationFlag) => {
        switch (flag) {
            case 'repetition': return 'Repetición detectada';
            case 'coherence': return 'Alerta de coherencia';
            case 'relevance': return 'Irrelevancia de tarea';
            case 'latency': return 'Latencia alta';
            default: return 'Problema desconocido';
        }
    };

    const getAlertSeverityColor = (score: number) => {
        if (score >= 80) return 'text-[#32d74b]';
        if (score >= 50) return 'text-[#ffd60a]';
        return 'text-[#ff453a]';
    };

    const getAlertBarColor = (score: number) => {
        if (score >= 80) return 'bg-[#32d74b]';
        if (score >= 50) return 'bg-[#ffd60a]';
        return 'bg-[#ff453a]';
    };

    return (
        <div className="p-4 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <div className="text-[10px] text-[#86868b] uppercase tracking-widest font-bold mb-1">Calidad de Razonamiento</div>
                    <div className={`text-3xl font-bold ${getAlertSeverityColor(score)}`}>
                        {score}%
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-[10px] text-[#86868b] uppercase tracking-widest font-bold mb-1">Último Análisis</div>
                    <div className="text-xs text-[#f5f5f7] font-mono">
                        {new Date(lastCheck).toLocaleTimeString()}
                    </div>
                </div>
            </div>

            {/* Quality Progress Bar */}
            <div className="w-full h-1.5 bg-[#1c1c1e] rounded-full overflow-hidden">
                <div
                    className={`h-full transition-all duration-1000 ${getAlertBarColor(score)}`}
                    style={{ width: `${score}%` }}
                />
            </div>

            {/* Alerts Section */}
            <div className="space-y-3">
                <div className="text-[10px] text-[#86868b] uppercase tracking-widest font-bold">Estado de Salud</div>

                {alerts.length === 0 ? (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-[#32d74b]/10 border border-[#32d74b]/20">
                        <CheckCircle size={16} className="text-[#32d74b]" />
                        <div className="text-xs text-[#32d74b]">Todas las métricas dentro del rango nominal.</div>
                    </div>
                ) : (
                    alerts.map((alert) => (
                        <div key={alert} className="flex items-center gap-3 p-3 rounded-lg bg-[#ff453a]/10 border border-[#ff453a]/20">
                            <AlertTriangle size={16} className="text-[#ff453a]" />
                            <div className="text-xs text-[#ff453a]">
                                <span className="font-bold">{getAlertLabel(alert)}</span>: Automated detection triggered.
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* System Info */}
            <div className="p-3 rounded-lg bg-[#1c1c1e] border border-[#2c2c2e]">
                <div className="text-[10px] text-[#86868b] uppercase tracking-widest font-bold mb-2">GICS Context</div>
                <div className="text-xs text-[#86868b] leading-relaxed">
                    Reasoning quality is evaluated using GICS (Gred In-Context Scoring).
                    The model monitors for entropy spikes, semantic repetition, and plan divergence.
                </div>
            </div>
        </div>
    );
};
