import MeshDeviceCard from '../components/mesh/MeshDeviceCard';
import MeshStatusBar from '../components/mesh/MeshStatusBar';
import { useMeshService } from '../hooks/useMeshService';

export default function MeshView() {
    const {
        status, devices, profiles,
        isLoading, error,
        approveDevice, refuseDevice, removeDevice,
    } = useMeshService();

    return (
        <div className="p-6 space-y-6 max-w-6xl mx-auto">
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-semibold text-zinc-100">GIMO Mesh</h1>
                {isLoading && <span className="text-xs text-zinc-500">Updating...</span>}
            </div>

            {error && (
                <div className="text-sm text-red-400 bg-red-900/20 px-3 py-2 rounded">
                    {error}
                </div>
            )}

            <MeshStatusBar status={status} />

            {devices.length === 0 && !isLoading && (
                <div className="text-center py-12 text-zinc-500">
                    No devices enrolled. Use the CLI or API to enroll devices.
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {devices.map(device => (
                    <MeshDeviceCard
                        key={device.device_id}
                        device={device}
                        onApprove={approveDevice}
                        onRefuse={refuseDevice}
                        onRemove={removeDevice}
                    />
                ))}
            </div>

            {/* Thermal profiles summary */}
            {profiles.length > 0 && (
                <div className="space-y-3">
                    <h2 className="text-sm font-medium text-zinc-300">Thermal Profiles</h2>
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs text-zinc-300">
                            <thead>
                                <tr className="border-b border-zinc-700 text-zinc-400">
                                    <th className="text-left py-2 px-2">Device</th>
                                    <th className="text-right px-2">Health</th>
                                    <th className="text-right px-2">Events</th>
                                    <th className="text-right px-2">Lockouts</th>
                                    <th className="text-right px-2">Duty Cycle</th>
                                    <th className="text-right px-2">Worst CPU</th>
                                    <th className="text-right px-2">Worst GPU</th>
                                </tr>
                            </thead>
                            <tbody>
                                {profiles.map(p => (
                                    <tr key={p.device_id} className="border-b border-zinc-800">
                                        <td className="py-1.5 px-2">{p.device_id}</td>
                                        <td className="text-right px-2">{p.health_score.toFixed(0)}%</td>
                                        <td className="text-right px-2">{p.total_events}</td>
                                        <td className="text-right px-2">{p.lockouts}</td>
                                        <td className="text-right px-2">
                                            {p.recommended_duty_cycle_min > 0 ? `${p.recommended_duty_cycle_min.toFixed(0)}m` : '--'}
                                        </td>
                                        <td className="text-right px-2">{p.worst_cpu_temp > 0 ? `${p.worst_cpu_temp.toFixed(0)}°` : '--'}</td>
                                        <td className="text-right px-2">{p.worst_gpu_temp > 0 ? `${p.worst_gpu_temp.toFixed(0)}°` : '--'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
