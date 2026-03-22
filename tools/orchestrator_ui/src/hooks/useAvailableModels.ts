import { useState, useEffect } from 'react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

export interface ModelItem {
    id: string;
    label: string;
    installed: boolean;
    downloadable?: boolean;
    context_window?: number;
    size?: string;
    quality_tier?: string;
}

export interface ProviderModelsResponse {
    provider_type: string;
    installed_models: ModelItem[];
    available_models: ModelItem[];
    recommended_models: ModelItem[];
    can_install: boolean;
    install_method: string;
    auth_modes_supported: string[];
    warnings: string[];
}

export const useAvailableModels = () => {
    const [models, setModels] = useState<ModelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let mounted = true;
        const fetchModels = async () => {
            try {
                const res = await fetchWithRetry(`${API_BASE}/ops/provider/models`, {
                    credentials: 'include'
                });
                if (!res.ok) throw new Error('Failed to fetch models');
                const data: ProviderModelsResponse = await res.json();
                if (!mounted) return;

                // Combine and deduplicate models
                const allModels = [...data.installed_models, ...data.available_models, ...data.recommended_models];
                const uniqueModels = Array.from(new Map(allModels.map(item => [item.id, item])).values());

                setModels(uniqueModels);
                setError(null);
            } catch (err: any) {
                if (!mounted) return;
                setError(err.message || 'Error loading models');
                setModels([]); // Fallback handled by UI
            } finally {
                if (mounted) setLoading(false);
            }
        };

        fetchModels();
        return () => { mounted = false; };
    }, []);

    return { models, loading, error };
};
