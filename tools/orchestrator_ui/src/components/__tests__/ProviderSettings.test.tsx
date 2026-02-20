import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ProviderSettings } from '../ProviderSettings';

const mocks = vi.hoisted(() => {
    const loadProvidersMock = vi.fn();
    const loadCatalogMock = vi.fn().mockResolvedValue({});
    const validateProviderMock = vi.fn().mockResolvedValue({ valid: true, health: 'ok', warnings: [] });
    const saveActiveProviderMock = vi.fn().mockResolvedValue({});
    const installModelMock = vi
        .fn()
        .mockResolvedValue({ status: 'queued', message: 'Install queued', job_id: 'job-1', progress: 0 });
    const getInstallJobMock = vi
        .fn()
        .mockResolvedValue({ status: 'done', message: 'ok', progress: 1, job_id: 'job-1' });
    const addToastMock = vi.fn();
    return {
        loadProvidersMock,
        loadCatalogMock,
        validateProviderMock,
        saveActiveProviderMock,
        installModelMock,
        getInstallJobMock,
        addToastMock,
    };
});

vi.mock('../../hooks/useProviders', () => ({
    useProviders: () => ({
        providerCapabilities: {
            openai: { auth_modes_supported: ['api_key'], requires_remote_api: true },
            codex: { auth_modes_supported: ['api_key', 'account'], requires_remote_api: true },
            ollama_local: { auth_modes_supported: ['none'], requires_remote_api: false },
        },
        effectiveState: { active: 'p1', model_id: 'qwen2.5-coder:7b' },
        catalogs: {
            openai: {
                provider_type: 'openai',
                installed_models: [{ id: 'gpt-4o-mini', label: 'gpt-4o-mini', installed: true, downloadable: false }],
                available_models: [{ id: 'gpt-4.1-mini', label: 'gpt-4.1-mini', installed: false, downloadable: false }],
                recommended_models: [{ id: 'gpt-4o-mini', label: 'gpt-4o-mini', installed: true, downloadable: false }],
                can_install: false,
                install_method: 'manual',
                auth_modes_supported: ['api_key'],
                warnings: [],
            },
            codex: {
                provider_type: 'codex',
                installed_models: [{ id: 'gpt-4o-mini', label: 'gpt-4o-mini', installed: true, downloadable: false }],
                available_models: [{ id: 'gpt-4o', label: 'gpt-4o', installed: false, downloadable: false }],
                recommended_models: [{ id: 'gpt-4o-mini', label: 'gpt-4o-mini', installed: true, downloadable: false }],
                can_install: false,
                install_method: 'manual',
                auth_modes_supported: ['api_key', 'account'],
                warnings: [],
            },
            ollama_local: {
                provider_type: 'ollama_local',
                installed_models: [{ id: 'llama3.1:8b', label: 'llama3.1:8b', installed: true, downloadable: true }],
                available_models: [{ id: 'qwen2.5-coder:7b', label: 'qwen2.5-coder:7b', installed: false, downloadable: true }],
                recommended_models: [{ id: 'qwen2.5-coder:7b', label: 'qwen2.5-coder:7b', installed: false, downloadable: true }],
                can_install: true,
                install_method: 'command',
                auth_modes_supported: ['none'],
                warnings: [],
            },
        },
        catalogLoading: {},
        providers: [
            {
                id: 'p1',
                type: 'ollama_local',
                is_local: true,
                model: 'qwen2.5-coder:7b',
                config: { model: 'qwen2.5-coder:7b' },
                capabilities: { auth_modes_supported: ['none'] },
            },
            {
                id: 'p2',
                type: 'groq',
                is_local: false,
                model: 'llama-3.3-70b-versatile',
                config: { model: 'llama-3.3-70b-versatile' },
                capabilities: { auth_modes_supported: ['api_key'] },
            },
        ],
        nodes: {
            'node-a': {
                id: 'node-a',
                name: 'The Handheld',
                type: 'edge',
                max_concurrency: 2,
                current_load: 1,
            },
        },
        loading: false,
        loadProviders: mocks.loadProvidersMock,
        loadCatalog: mocks.loadCatalogMock,
        installModel: mocks.installModelMock,
        getInstallJob: mocks.getInstallJobMock,
        validateProvider: mocks.validateProviderMock,
        saveActiveProvider: mocks.saveActiveProviderMock,
        removeProvider: vi.fn(),
        testProvider: vi.fn(),
    }),
}));

vi.mock('../Toast', () => ({
    useToast: () => ({ addToast: mocks.addToastMock }),
}));

describe('ProviderSettings', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renderiza y carga providers al montar', () => {
        render(<ProviderSettings />);
        expect(screen.getByText('Provider Settings')).toBeInTheDocument();
        expect(mocks.loadProvidersMock).toHaveBeenCalled();
    });

    it('ejecuta validación y guardar provider activo', async () => {
        render(<ProviderSettings />);
        fireEvent.click(screen.getByText('Test connection'));
        fireEvent.click(screen.getByText('Save as active provider'));

        await waitFor(() => {
            expect(mocks.validateProviderMock).toHaveBeenCalled();
            expect(mocks.saveActiveProviderMock).toHaveBeenCalled();
        });
    });

    it('recarga catálogo al cambiar provider type', async () => {
        render(<ProviderSettings />);
        const providerTypeSelect = screen.getByDisplayValue('openai');
        fireEvent.change(providerTypeSelect, { target: { value: 'codex' } });

        await waitFor(() => {
            expect(mocks.loadCatalogMock).toHaveBeenCalledWith('codex');
        });
    });
});
