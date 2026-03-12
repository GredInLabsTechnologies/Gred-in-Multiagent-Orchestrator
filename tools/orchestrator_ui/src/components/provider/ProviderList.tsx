import React from 'react';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { Cloud, Cpu, Trash2, Activity } from 'lucide-react';
import { ProviderInfo } from '../../types';

const PROVIDER_LABELS: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    google: 'Google',
    mistral: 'Mistral',
    cohere: 'Cohere',
    deepseek: 'DeepSeek',
    qwen: 'Qwen',
    moonshot: 'Moonshot',
    zai: 'Z.ai',
    minimax: 'MiniMax',
    baidu: 'Baidu',
    tencent: 'Tencent',
    bytedance: 'ByteDance',
    iflytek: 'iFlyTek',
    '01-ai': '01.AI',
    codex: 'Codex CLI',
    claude: 'Anthropic (Claude CLI)',
    together: 'Together',
    fireworks: 'Fireworks',
    replicate: 'Replicate',
    huggingface: 'HuggingFace',
    'azure-openai': 'Azure OpenAI',
    'aws-bedrock': 'AWS Bedrock',
    'vertex-ai': 'Vertex AI',
    ollama: 'Ollama',
    vllm: 'vLLM',
    'llama-cpp': 'llama.cpp',
    tgi: 'Text Generation Inference (TGI)',
    ollama_local: 'Ollama (Local)',
    groq: 'Groq',
    openrouter: 'OpenRouter',
    custom_openai_compatible: 'OpenAI Compatible',
};

interface ProviderListProps {
    providers: ProviderInfo[];
    onTest: (id: string) => Promise<{ healthy: boolean; message: string }>;
    onRemove: (id: string) => Promise<void>;
    addToast: (msg: string, type?: 'error' | 'success' | 'info') => void;
}

export const ProviderList: React.FC<ProviderListProps> = ({ providers, onTest, onRemove, addToast }) => {
    return (
        <div className="space-y-3">
            <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">Providers Activos</h3>
            {providers.length === 0 && (
                <div className="text-text-secondary text-center py-6 bg-surface-0/60 rounded border border-dashed border-border-primary">
                    Sin providers configurados. Gred funcionará en modo local limitado.
                </div>
            )}
            {providers.map((p) => (
                <Card key={p.id} className="bg-surface-2 border-border-primary p-4 flex items-center justify-between group hover:border-surface-3 transition-colors">
                    <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg ${p.is_local ? 'bg-emerald-500/10 text-emerald-400' : 'bg-blue-500/10 text-blue-400'}`}>
                            {p.is_local ? <Cpu className="w-5 h-5" /> : <Cloud className="w-5 h-5" />}
                        </div>
                        <div>
                            <div className="font-medium text-text-primary">{p.config?.display_name || PROVIDER_LABELS[p.type] || p.id}</div>
                            <div className="text-xs text-text-secondary uppercase">{PROVIDER_LABELS[p.type] || p.type} • {p.is_local ? 'Local' : 'Cloud'}</div>
                            {p.capabilities && (
                                <div className="text-[10px] text-text-secondary mt-1">
                                    auth: {(p.capabilities.auth_modes_supported || []).join(', ') || 'n/a'}
                                </div>
                            )}
                            <div className="text-[10px] text-text-secondary">model: {p.model || p.config?.model || 'n/a'}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={async () => {
                                const result = await onTest(p.id);
                                addToast(result.message, result.healthy ? 'success' : 'error');
                            }}
                            className="text-text-secondary hover:text-text-primary"
                        >
                            <Activity className="w-4 h-4 mr-1" />
                            Probar
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={async () => {
                                try {
                                    await onRemove(p.id);
                                    addToast(`Provider ${p.config?.display_name || p.id} eliminado`, 'info');
                                } catch (err: any) {
                                    addToast(err?.message || 'No se pudo eliminar el provider', 'error');
                                }
                            }}
                            className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                        >
                            <Trash2 className="w-4 h-4" />
                        </Button>
                    </div>
                </Card>
            ))}
        </div>
    );
};
