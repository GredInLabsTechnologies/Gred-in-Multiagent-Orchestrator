import React from 'react';

interface SkeletonProps {
    className?: string;
    lines?: number;
}

/**
 * @deprecated 2026-04-15. Use Tailwind pattern: <div className="animate-pulse bg-zinc-700 rounded h-N" />.
 * Will be removed once no consumers remain. Currently unused (no internal imports detected),
 * but kept temporarily to avoid breaking any external consumer not yet migrated.
 */
export const Skeleton: React.FC<SkeletonProps> = ({ className = '', lines = 1 }) => {
    return (
        <div className="space-y-2">
            {Array.from({ length: lines }).map((_, i) => (
                <div
                    key={i}
                    className={`skeleton h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'} ${className}`}
                />
            ))}
        </div>
    );
};
