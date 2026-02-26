import React from 'react';

interface Props extends React.PropsWithChildren {
    visualState?: 'idle' | 'verifying' | 'success' | 'error';
    style?: React.CSSProperties;
}

export const LoginGlassCard: React.FC<Props> = ({ children, visualState = 'idle', style }) => {
    const stateClass =
        visualState === 'verifying'
            ? 'border-accent-primary/60 shadow-[0_24px_80px_rgba(59,130,246,0.18)]'
            : visualState === 'success'
                ? 'border-accent-trust/60 shadow-[0_24px_80px_rgba(90,159,143,0.22)]'
                : visualState === 'error'
                    ? 'border-accent-alert/55 shadow-[0_24px_80px_rgba(200,84,80,0.2)]'
                    : 'border-border-primary shadow-[0_24px_80px_rgba(8,12,20,0.6)]';

    return (
        <div
            style={style}
            className={`relative z-10 w-full max-w-lg rounded-2xl border bg-surface-2/60 backdrop-blur-lg p-6 sm:p-8 transition-all duration-300 ${stateClass}`}
        >
            <div
                className={`pointer-events-none absolute inset-0 rounded-2xl transition-opacity duration-300 ${visualState === 'verifying'
                    ? 'opacity-100 bg-[radial-gradient(circle_at_20%_0%,rgba(59,130,246,0.12),transparent_45%)]'
                    : visualState === 'success'
                        ? 'opacity-100 bg-[radial-gradient(circle_at_20%_0%,rgba(90,159,143,0.12),transparent_45%)]'
                        : visualState === 'error'
                            ? 'opacity-100 bg-[radial-gradient(circle_at_20%_0%,rgba(200,84,80,0.10),transparent_45%)]'
                            : 'opacity-0'
                    }`}
            />
            {children}
        </div>
    );
};
