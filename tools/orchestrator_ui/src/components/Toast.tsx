import React, { createContext, useContext, useState, useCallback } from 'react';

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

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const addToast = useCallback((message: string, type: Toast['type'] = 'info') => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
        setToasts(prev => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 4000);
    }, []);

    const removeToast = useCallback((id: string) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    }, []);

    return (
        <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
            {children}
            <div className="fixed bottom-16 right-4 z-[100] space-y-2">
                {toasts.map(toast => (
                    <div
                        key={toast.id}
                        className={`toast-enter px-4 py-2.5 rounded-xl border text-xs font-medium shadow-2xl backdrop-blur-xl cursor-pointer
                            ${toast.type === 'success'
                                ? 'bg-[#32d74b]/10 border-[#32d74b]/20 text-[#32d74b]'
                                : toast.type === 'error'
                                    ? 'bg-[#ff3b30]/10 border-[#ff3b30]/20 text-[#ff3b30]'
                                    : 'bg-[#0a84ff]/10 border-[#0a84ff]/20 text-[#0a84ff]'
                            }`}
                        onClick={() => removeToast(toast.id)}
                    >
                        {toast.message}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
};
