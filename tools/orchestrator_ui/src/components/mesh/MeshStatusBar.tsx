import type { MeshStatus } from '../../types';

interface Props {
    status: MeshStatus | null;
}

export default function MeshStatusBar({ status }: Props) {
    if (!status) return null;

    return (
        <div className="flex items-center gap-4 px-4 py-2 bg-zinc-900 rounded-lg border border-zinc-700 text-sm">
            <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${status.mesh_enabled ? 'bg-green-500' : 'bg-zinc-500'}`} />
                <span className="text-zinc-300">Mesh {status.mesh_enabled ? 'ON' : 'OFF'}</span>
            </div>
            <div className="text-zinc-400">
                {status.devices_connected}/{status.device_count} connected
            </div>
            {Object.entries(status.devices_by_mode).map(([mode, count]) => (
                <div key={mode} className="text-zinc-500">
                    <span className="text-zinc-400">{count}</span> {mode}
                </div>
            ))}
        </div>
    );
}
