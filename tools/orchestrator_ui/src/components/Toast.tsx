import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

interface Toast {
    id: string;
    message: string;
    type: 'success' | 'error' | 'info';
}

interface ToastContextValue {
    toasts: Toast[];
    addToast: (message: string, type?: Toast['type']) => void;
    removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export const useToast = () => {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error('useToast must be used within ToastProvider');
    return ctx;
};

const ICONS: Record<Toast['type'], typeof CheckCircle2> = {
    success: CheckCircle2,
    error: AlertCircle,
    info: Info,
};

const STYLES: Record<Toast['type'], string> = {
    success: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
    error: 'bg-red-500/10 border-red-500/20 text-red-400',
    info: 'bg-accent-primary/10 border-accent-primary/20 text-accent-primary',
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const dismissToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    const addToast = useCallback((message: string, type: Toast['type'] = 'info') => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
        setToasts((prev) => [...prev, { id, message, type }]);
        setTimeout(() => dismissToast(id), 4000);
    }, [dismissToast]);

    const removeToast = dismissToast;

    const contextValue = useMemo(() => ({ toasts, addToast, removeToast }), [toasts, addToast, removeToast]);

    return (
        <ToastContext.Provider value={contextValue}>
            {children}
            <div
                className="fixed bottom-16 right-4 z-[100] space-y-2 pointer-events-none"
                aria-live="polite"
                aria-atomic="false"
            >
                <AnimatePresence initial={false}>
                    {toasts.map((toast, i) => {
                        const Icon = ICONS[toast.type];
                        return (
                            <motion.div
                                key={toast.id}
                                initial={{ opacity: 0, x: 40, scale: 0.95 }}
                                animate={{ opacity: 1, x: 0, scale: 1 }}
                                exit={{ opacity: 0, x: 40, scale: 0.95 }}
                                transition={{ type: 'spring', stiffness: 500, damping: 30, delay: i * 0.05 }}
                                className={`pointer-events-auto flex items-center gap-2.5 px-4 py-2.5 rounded-xl border text-xs font-medium shadow-lg shadow-black/20 backdrop-blur-xl cursor-pointer max-w-sm ${STYLES[toast.type]}`}
                                onClick={() => removeToast(toast.id)}
                                role="status"
                            >
                                <Icon size={14} className="shrink-0" />
                                <span className="flex-1">{toast.message}</span>
                                <X size={12} className="shrink-0 opacity-40 hover:opacity-100 transition-opacity" />
                            </motion.div>
                        );
                    })}
                </AnimatePresence>
            </div>
        </ToastContext.Provider>
    );
};
