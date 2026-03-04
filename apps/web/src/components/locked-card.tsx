"use client";

import type { ReactNode } from "react";
import { Lock } from "lucide-react";

interface LockedCardProps {
    title: string;
    children: ReactNode;
    ctaText: string;
    onAction: () => void;
    className?: string;
}

export function LockedCard({ title, children, ctaText, onAction, className = "" }: LockedCardProps) {
    return (
        <div className={`rounded-xl border border-border bg-card overflow-hidden ${className}`}>
            {/* Card header */}
            <div className="px-6 pt-5 pb-3 flex items-center justify-between">
                <h3 className="font-semibold text-sm text-foreground">{title}</h3>
                <Lock size={14} className="text-muted-foreground" />
            </div>

            {/* Blurred preview + overlay */}
            <div className="relative px-6 pb-6">
                {/* Preview content — blurred */}
                <div className="blur-sm select-none pointer-events-none opacity-60">
                    {children}
                </div>

                {/* Overlay CTA */}
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-card/70 backdrop-blur-[2px]">
                    <Lock size={20} className="text-muted-foreground" />
                    <button
                        type="button"
                        onClick={onAction}
                        className="px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-md"
                    >
                        {ctaText}
                    </button>
                </div>
            </div>
        </div>
    );
}
