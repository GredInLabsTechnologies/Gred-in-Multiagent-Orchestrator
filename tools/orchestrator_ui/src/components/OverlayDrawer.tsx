import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';

interface OverlayDrawerProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    width?: 'sm' | 'md' | 'lg' | 'xl' | 'full';
    children: React.ReactNode;
}

const widthMap = {
    sm: 'max-w-md',
    md: 'max-w-xl',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
    full: 'max-w-[90vw]',
};

export const OverlayDrawer: React.FC<OverlayDrawerProps> = ({
    isOpen,
    onClose,
    title,
    width = 'md',
    children,
}) => {
    const closeRef = useRef<HTMLButtonElement>(null);

    /* Close on Escape */
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        globalThis.addEventListener('keydown', handler);
        return () => globalThis.removeEventListener('keydown', handler);
    }, [isOpen, onClose]);

    /* Auto-focus close button for keyboard a11y */
    useEffect(() => {
        if (isOpen) {
            requestAnimationFrame(() => closeRef.current?.focus());
        }
    }, [isOpen]);

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]"
                        onClick={onClose}
                        aria-hidden="true"
                    />

                    {/* Drawer */}
                    <motion.aside
                        role="dialog"
                        aria-modal="true"
                        aria-label={title}
                        initial={{ x: '100%', opacity: 0.8 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: '100%', opacity: 0.8 }}
                        transition={{ type: 'spring', stiffness: 400, damping: 35 }}
                        className={`fixed right-0 top-0 bottom-0 z-50 ${widthMap[width]} w-full flex flex-col
                            bg-surface-0/85 backdrop-blur-2xl border-l border-white/[0.06]
                            shadow-[-8px_0_32px_rgba(0,0,0,0.4)]`}
                    >
                        {/* Header */}
                        <div className="h-12 px-5 flex items-center justify-between border-b border-white/[0.04] shrink-0">
                            <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
                            <button
                                ref={closeRef}
                                onClick={onClose}
                                className="w-7 h-7 rounded-lg flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-white/[0.06] transition-colors active:scale-[0.95]"
                                aria-label="Cerrar panel"
                            >
                                <X size={14} />
                            </button>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto custom-scrollbar">
                            {children}
                        </div>
                    </motion.aside>
                </>
            )}
        </AnimatePresence>
    );
};
