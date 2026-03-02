import { memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Edit2, Save, X, Plus, Play } from 'lucide-react';
import { useGraphStore } from './useGraphStore';

interface GraphToolbarProps {
    onEnterEdit: () => void;
    onExitEdit: () => void;
    onAddNode: () => void;
    onSaveDraft: () => void;
    onExecute: () => void;
}

export const GraphToolbar = memo(({
    onEnterEdit,
    onExitEdit,
    onAddNode,
    onSaveDraft,
    onExecute,
}: GraphToolbarProps) => {
    const isEditMode = useGraphStore((s) => s.isEditMode);
    const isSaving = useGraphStore((s) => s.isSaving);
    const isExecuting = useGraphStore((s) => s.isExecuting);
    const activePlanId = useGraphStore((s) => s.activePlanId);

    return (
        <motion.div
            layout
            className="flex items-center bg-surface-1/85 backdrop-blur-2xl rounded-2xl border border-white/[0.06] p-1.5 shadow-xl shadow-black/30"
        >
            <AnimatePresence mode="wait" initial={false}>
                {!isEditMode ? (
                    <motion.button
                        key="enter-edit"
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        onClick={onEnterEdit}
                        className="flex items-center gap-2 px-4 py-2 hover:bg-white/[0.06] text-text-secondary hover:text-text-primary rounded-xl transition-colors text-[11px] font-medium"
                    >
                        <Edit2 size={14} />
                        Modo Edicion
                    </motion.button>
                ) : (
                    <motion.div
                        key="edit-tools"
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                        className="flex items-center gap-0.5"
                    >
                        <button
                            onClick={onAddNode}
                            className="flex items-center gap-2 px-3 py-2 hover:bg-white/[0.06] text-text-secondary hover:text-text-primary rounded-xl transition-colors text-[11px] font-medium"
                        >
                            <Plus size={14} />
                            Nodo
                        </button>

                        <div className="w-px h-5 bg-white/[0.06] mx-1" />

                        <span className="px-2 py-1 text-[9px] text-text-tertiary hidden sm:inline">
                            Doble click = crear &middot; Arrastra handles = conectar
                        </span>

                        <div className="w-px h-5 bg-white/[0.06] mx-1" />

                        <button
                            onClick={onSaveDraft}
                            disabled={isSaving}
                            className="flex items-center gap-2 px-3 py-2 bg-accent-trust/10 text-accent-trust hover:bg-accent-trust/20 rounded-xl transition-colors text-[11px] font-bold disabled:opacity-50"
                        >
                            <Save size={14} />
                            {isSaving ? 'Guardando...' : 'Guardar'}
                        </button>

                        <button
                            onClick={onExecute}
                            disabled={isExecuting || !activePlanId}
                            className="flex items-center gap-2 px-3 py-2 bg-accent-primary/10 text-accent-primary hover:bg-accent-primary/20 disabled:opacity-50 rounded-xl transition-colors text-[11px] font-bold"
                        >
                            <Play size={14} />
                            Ejecutar
                        </button>

                        <div className="w-px h-5 bg-white/[0.06] mx-1" />

                        <button
                            onClick={onExitEdit}
                            className="flex items-center justify-center w-8 h-8 hover:bg-accent-alert/10 text-text-secondary hover:text-accent-alert rounded-xl transition-colors"
                            title="Cancelar edicion"
                        >
                            <X size={14} />
                        </button>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
});

GraphToolbar.displayName = 'GraphToolbar';
