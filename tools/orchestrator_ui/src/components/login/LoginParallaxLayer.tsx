import React, { useMemo } from 'react';

interface Props {
    mouseX: number;
    mouseY: number;
    reducedMotion: boolean;
}

export const LoginParallaxLayer: React.FC<Props> = ({ mouseX, mouseY, reducedMotion }) => {
    const styleA = useMemo(() => ({
        transform: reducedMotion ? 'none' : `translate(${mouseX * 0.012}px, ${mouseY * 0.012}px)`,
    }), [mouseX, mouseY, reducedMotion]);

    const styleB = useMemo(() => ({
        transform: reducedMotion ? 'none' : `translate(${mouseX * -0.018}px, ${mouseY * -0.018}px)`,
    }), [mouseX, mouseY, reducedMotion]);

    const styleC = useMemo(() => ({
        transform: reducedMotion ? 'none' : `translate(${mouseX * 0.008}px, ${mouseY * -0.01}px)`,
    }), [mouseX, mouseY, reducedMotion]);

    return (
        <>
            <div style={styleA} className="pointer-events-none absolute -top-16 -left-16 h-64 w-64 rounded-full bg-accent-primary/15 blur-3xl transition-transform duration-300 ease-out" />
            <div style={styleB} className="pointer-events-none absolute -bottom-20 -right-20 h-72 w-72 rounded-full bg-accent-trust/10 blur-3xl transition-transform duration-300 ease-out" />
            <div style={styleC} className="pointer-events-none absolute top-1/4 right-1/3 h-44 w-44 rounded-full bg-accent-approval/10 blur-3xl transition-transform duration-500 ease-out" />
        </>
    );
};
