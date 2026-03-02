import { memo } from 'react';
import { EdgeProps, getBezierPath } from 'reactflow';

/** Map stroke CSS var back to a logical status for animation decisions */
function inferStatusFromStroke(stroke: string): string {
    if (stroke.includes('running') || stroke.includes('3b82f6')) return 'running';
    if (stroke.includes('done') || stroke.includes('trust') || stroke.includes('5a9f8f')) return 'done';
    if (stroke.includes('error') || stroke.includes('alert') || stroke.includes('c85450')) return 'error';
    return 'pending';
}

/**
 * Premium animated edge with semantic coloring and flow particles.
 * - pending: dim gray
 * - running: animated blue particles
 * - done: solid green
 * - error: red pulse
 */
export const AnimatedEdge = memo(({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    style = {},
    selected,
}: EdgeProps) => {
    const [edgePath] = getBezierPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
    });

    // Derive visual state from style.stroke (set by normalizeServerEdges) or data.status
    const stroke = style?.stroke as string || 'var(--text-tertiary)';
    const status = data?.status || inferStatusFromStroke(stroke);
    const isRunning = status === 'running' || stroke === 'var(--status-running)';
    const isError = status === 'error' || status === 'failed' || stroke === 'var(--status-error)';

    return (
        <g className="react-flow__edge-group">
            {/* Invisible fat path for easier click target */}
            <path
                d={edgePath}
                fill="none"
                stroke="transparent"
                strokeWidth={20}
                className="react-flow__edge-interaction"
            />

            {/* Glow layer for running edges */}
            {isRunning && (
                <path
                    d={edgePath}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={6}
                    strokeOpacity={0.15}
                    className="animate-pulse"
                />
            )}

            {/* Main edge path */}
            <path
                id={id}
                d={edgePath}
                fill="none"
                stroke={stroke}
                strokeWidth={selected ? 3 : 2}
                strokeLinecap="round"
                className={`transition-all duration-300 ${isError ? 'animate-pulse' : ''}`}
                style={{
                    ...(isRunning
                        ? {
                              strokeDasharray: '8 4',
                              animation: 'edge-flow 1s linear infinite',
                          }
                        : {}),
                }}
            />

        </g>
    );
});

AnimatedEdge.displayName = 'AnimatedEdge';
