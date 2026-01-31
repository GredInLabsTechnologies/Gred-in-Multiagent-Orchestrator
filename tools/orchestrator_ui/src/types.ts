// API Configuration
export const API_BASE = import.meta.env.VITE_API_URL || `http://${globalThis.location?.hostname ?? 'localhost'}:8001`;

export interface RepoInfo {
    name: string;
    path: string;
}
