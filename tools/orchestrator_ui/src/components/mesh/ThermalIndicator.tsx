interface Props {
    cpu_temp_c: number;
    gpu_temp_c: number;
    battery_temp_c: number;
    thermal_throttled: boolean;
    thermal_locked_out: boolean;
}

function tempColor(temp: number, warnAt: number, critAt: number): string {
    if (temp < 0) return 'bg-zinc-600';
    if (temp >= critAt) return 'bg-red-500';
    if (temp >= warnAt) return 'bg-yellow-500';
    return 'bg-green-500';
}

function TempBar({ label, temp, warnAt, critAt }: { label: string; temp: number; warnAt: number; critAt: number }) {
    const pct = temp < 0 ? 0 : Math.min(100, (temp / critAt) * 100);
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-8 text-zinc-400">{label}</span>
            <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${tempColor(temp, warnAt, critAt)}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="w-10 text-right text-zinc-400">{temp < 0 ? '--' : `${temp.toFixed(0)}°`}</span>
        </div>
    );
}

export default function ThermalIndicator({ cpu_temp_c, gpu_temp_c, battery_temp_c, thermal_throttled, thermal_locked_out }: Props) {
    return (
        <div className="space-y-1">
            {thermal_locked_out && (
                <div className="text-xs font-semibold text-red-400 bg-red-900/30 px-2 py-0.5 rounded">LOCKOUT</div>
            )}
            {thermal_throttled && !thermal_locked_out && (
                <div className="text-xs font-semibold text-yellow-400 bg-yellow-900/30 px-2 py-0.5 rounded">THROTTLED</div>
            )}
            <TempBar label="CPU" temp={cpu_temp_c} warnAt={75} critAt={95} />
            <TempBar label="GPU" temp={gpu_temp_c} warnAt={80} critAt={95} />
            <TempBar label="BAT" temp={battery_temp_c} warnAt={40} critAt={50} />
        </div>
    );
}
