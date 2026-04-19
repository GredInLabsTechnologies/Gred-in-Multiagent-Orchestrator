import type { MeshDevice } from '../../types';
import ThermalIndicator from './ThermalIndicator';

interface Props {
    device: MeshDevice;
    onApprove?: (id: string) => void;
    onRefuse?: (id: string) => void;
    onRemove?: (id: string) => void;
}

const MODE_COLORS: Record<string, string> = {
    inference: 'bg-blue-600',
    utility: 'bg-purple-600',
    server: 'bg-amber-600',
    hybrid: 'bg-cyan-600',
};

const STATE_COLORS: Record<string, string> = {
    connected: 'bg-green-500',
    approved: 'bg-green-400',
    pending_approval: 'bg-yellow-500',
    reconnecting: 'bg-yellow-400',
    thermal_lockout: 'bg-red-500',
    refused: 'bg-red-400',
    offline: 'bg-zinc-500',
    discoverable: 'bg-blue-400',
};

export default function MeshDeviceCard({ device, onApprove, onRefuse, onRemove }: Props) {
    const d = device;
    const healthPct = Math.max(0, Math.min(100, d.health_score));
    const healthColor = healthPct > 70 ? 'bg-green-500' : healthPct > 40 ? 'bg-yellow-500' : 'bg-red-500';

    return (
        <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-4 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${STATE_COLORS[d.connection_state] || 'bg-zinc-500'}`} />
                    <span className="font-medium text-zinc-100 text-sm">{d.name || d.device_id}</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded ${MODE_COLORS[d.device_mode] || 'bg-zinc-600'} text-white`}>
                    {d.device_mode}
                </span>
            </div>

            {/* Status line */}
            <div className="flex items-center gap-3 text-xs text-zinc-400">
                <span>{d.connection_state.replace('_', ' ')}</span>
                <span>{d.operational_state}</span>
                {d.model_loaded && <span className="text-zinc-300">{d.model_loaded}</span>}
            </div>

            {/* Health bar */}
            <div className="space-y-1">
                <div className="flex justify-between text-xs">
                    <span className="text-zinc-400">Health</span>
                    <span className="text-zinc-300">{healthPct.toFixed(0)}%</span>
                </div>
                <div className="h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${healthColor}`} style={{ width: `${healthPct}%` }} />
                </div>
            </div>

            {/* Resource stats */}
            <div className="grid grid-cols-3 gap-2 text-xs text-center">
                <div>
                    <div className="text-zinc-400">CPU</div>
                    <div className="text-zinc-200">{d.cpu_percent.toFixed(0)}%</div>
                </div>
                <div>
                    <div className="text-zinc-400">RAM</div>
                    <div className="text-zinc-200">{d.ram_percent.toFixed(0)}%</div>
                </div>
                <div>
                    <div className="text-zinc-400">Battery</div>
                    <div className="text-zinc-200">{d.battery_percent < 0 ? '--' : `${d.battery_percent.toFixed(0)}%`}</div>
                </div>
            </div>

            {/* Thermal */}
            <ThermalIndicator
                cpu_temp_c={d.cpu_temp_c}
                gpu_temp_c={d.gpu_temp_c}
                battery_temp_c={d.battery_temp_c}
                thermal_throttled={d.thermal_throttled}
                thermal_locked_out={d.thermal_locked_out}
            />

            {/* Actions */}
            {d.connection_state === 'pending_approval' && (
                <div className="flex gap-2 pt-1">
                    {onApprove && (
                        <button onClick={() => onApprove(d.device_id)}
                            className="flex-1 text-xs px-2 py-1 bg-green-700 hover:bg-green-600 text-white rounded">
                            Approve
                        </button>
                    )}
                    {onRefuse && (
                        <button onClick={() => onRefuse(d.device_id)}
                            className="flex-1 text-xs px-2 py-1 bg-red-700 hover:bg-red-600 text-white rounded">
                            Refuse
                        </button>
                    )}
                </div>
            )}
            {onRemove && d.connection_state !== 'pending_approval' && (
                <button onClick={() => onRemove(d.device_id)}
                    className="w-full text-xs px-2 py-1 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 rounded">
                    Remove
                </button>
            )}
        </div>
    );
}
