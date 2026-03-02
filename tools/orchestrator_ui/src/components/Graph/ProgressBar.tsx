import { memo } from 'react';
import { motion } from 'framer-motion';
import { ProgressStats } from './useGraphStore';

interface ProgressBarProps {
    stats: ProgressStats;
}

export const ProgressBar = memo(({ stats }: ProgressBarProps) => (
    <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        className="bg-surface-1/85 backdrop-blur-2xl px-4 py-2.5 rounded-xl border border-white/[0.06] min-w-[220px] shadow-lg shadow-black/20"
    >
        <div className="flex justify-between items-center mb-1.5">
            <span className="text-[10px] text-text-primary font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-pulse" />
                Ejecucion en progreso
            </span>
            <span className="text-[10px] text-text-secondary font-mono">
                {stats.done} / {stats.total}
            </span>
        </div>
        <div className="h-1 w-full bg-white/[0.04] rounded-full overflow-hidden">
            <motion.div
                className="h-full bg-accent-primary rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${stats.percent}%` }}
                transition={{ type: 'spring', stiffness: 200, damping: 25 }}
            />
        </div>
    </motion.div>
));

ProgressBar.displayName = 'ProgressBar';
