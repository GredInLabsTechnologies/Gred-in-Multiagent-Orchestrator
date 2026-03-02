import { memo } from 'react';
import { motion } from 'framer-motion';
import { Trash2, Info } from 'lucide-react';
import { Node } from 'reactflow';
import { NODE_TYPES, ROLE_TEMPLATES } from './useGraphStore';

interface NodeEditorProps {
    node: Node;
    models: { id: string; label?: string }[];
    onUpdateField: (field: string, value: any) => void;
    onDelete: () => void;
}

export const NodeEditor = memo(({ node, models, onUpdateField, onDelete }: NodeEditorProps) => {
    const d = node.data;

    return (
        <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            className="w-[340px] max-h-[80vh] overflow-y-auto bg-surface-1/90 backdrop-blur-2xl border border-white/[0.06] rounded-2xl p-4 shadow-xl shadow-black/30"
        >
            <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-tertiary mb-3">
                Configuracion de Nodo
            </h3>

            <div className="space-y-3">
                {/* Name */}
                <Field label="Nombre">
                    <input
                        value={d?.label || ''}
                        onChange={(e) => onUpdateField('label', e.target.value)}
                        className="input-field"
                    />
                </Field>

                {/* Node Type */}
                <Field label="Tipo de Nodo">
                    <select
                        value={d?.node_type || 'worker'}
                        onChange={(e) => onUpdateField('node_type', e.target.value)}
                        className="input-field"
                    >
                        {NODE_TYPES.map((type) => (
                            <option key={type} value={type}>
                                {type}
                            </option>
                        ))}
                    </select>
                </Field>

                {/* Model */}
                <Field label="Modelo">
                    <select
                        value={d?.model || 'auto'}
                        onChange={(e) => onUpdateField('model', e.target.value)}
                        className="input-field"
                    >
                        <option value="auto">auto (usa el provider activo)</option>
                        {models.map((m) => (
                            <option key={m.id} value={m.id}>
                                {m.label || m.id}
                            </option>
                        ))}
                    </select>
                </Field>

                {/* Provider */}
                <Field label="Provider">
                    <select
                        value={d?.provider || 'auto'}
                        onChange={(e) => onUpdateField('provider', e.target.value)}
                        className="input-field"
                    >
                        <option value="auto">auto (provider activo)</option>
                        <option value="openai">OpenAI</option>
                        <option value="ollama">Ollama (local)</option>
                        <option value="groq">Groq</option>
                        <option value="openrouter">OpenRouter</option>
                        <option value="codex">Codex CLI</option>
                    </select>
                </Field>

                {/* Role Definition */}
                <Field label="Definicion de Rol">
                    <select
                        value=""
                        onChange={(e) => {
                            const tpl = ROLE_TEMPLATES[e.target.value];
                            if (tpl) onUpdateField('role_definition', tpl);
                        }}
                        className="input-field mb-1"
                    >
                        <option value="">Aplicar plantilla de rol...</option>
                        {NODE_TYPES.map((type) => (
                            <option key={type} value={type}>
                                {type}
                            </option>
                        ))}
                    </select>
                    <textarea
                        value={d?.role_definition || ''}
                        onChange={(e) => onUpdateField('role_definition', e.target.value)}
                        rows={3}
                        className="input-field resize-none"
                    />
                </Field>

                {/* Prompt */}
                <Field label="Prompt / Instructions">
                    <textarea
                        value={d?.prompt || ''}
                        onChange={(e) => onUpdateField('prompt', e.target.value)}
                        rows={6}
                        className="input-field resize-none"
                    />
                    <div className="flex items-start gap-2 text-[10px] text-text-secondary bg-blue-500/5 p-2 rounded-lg border border-blue-500/10 mt-1">
                        <Info size={12} className="shrink-0 mt-0.5" />
                        <span>
                            Las salidas de nodos dependientes se inyectaran automaticamente en el
                            contexto de este nodo.
                        </span>
                    </div>
                </Field>

                {/* Status + ID */}
                <div className="grid grid-cols-2 gap-2">
                    <Field label="Status">
                        <div className="input-field text-text-secondary">
                            {d?.status || 'pending'}
                        </div>
                    </Field>
                    <Field label="Node ID">
                        <div className="input-field font-mono text-[11px] text-text-secondary truncate">
                            {node.id}
                        </div>
                    </Field>
                </div>

                {/* Error display */}
                {d?.error && (
                    <Field label="Error" labelColor="text-red-300">
                        <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-200 whitespace-pre-wrap">
                            {d.error}
                        </div>
                    </Field>
                )}

                {/* Output display */}
                {d?.output && (
                    <Field label="Output">
                        <div className="max-h-36 overflow-y-auto bg-surface-3/60 border border-white/[0.04] rounded-lg px-3 py-2 text-xs text-text-secondary whitespace-pre-wrap">
                            {d.output}
                        </div>
                    </Field>
                )}

                {/* Delete */}
                <button
                    onClick={onDelete}
                    className="w-full flex items-center justify-center gap-2 mt-2 px-3 py-2 rounded-xl border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20 text-xs font-semibold transition-colors"
                >
                    <Trash2 size={14} />
                    Eliminar nodo
                </button>
            </div>
        </motion.div>
    );
});

NodeEditor.displayName = 'NodeEditor';

/* ── Shared Field wrapper ──────────────────────────── */

function Field({
    label,
    labelColor,
    children,
}: {
    label: string;
    labelColor?: string;
    children: React.ReactNode;
}) {
    return (
        <div>
            <label
                className={`text-[10px] uppercase tracking-wider ${labelColor || 'text-text-tertiary'}`}
            >
                {label}
            </label>
            <div className="mt-1">{children}</div>
        </div>
    );
}
