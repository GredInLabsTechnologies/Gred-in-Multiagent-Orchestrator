import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    fetchWithRetryMock: vi.fn(),
    loadCatalogMock: vi.fn(),
    installModelMock: vi.fn(),
    getInstallJobMock: vi.fn(),
    listCliDependenciesMock: vi.fn(),
    installCliDependencyMock: vi.fn(),
    getCliDependencyInstallJobMock: vi.fn(),
    startCodexDeviceLoginMock: vi.fn(),
    startClaudeLoginMock: vi.fn(),
    fetchCliAuthStatusMock: vi.fn(),
    cliLogoutMock: vi.fn(),
}));

vi.mock('../../lib/fetchWithRetry', () => ({
    fetchWithRetry: mocks.fetchWithRetryMock,
}));

vi.mock('../useProviderCatalog', () => ({
    useProviderCatalog: () => ({
        catalogs: {},
        catalogLoading: {},
        loadCatalog: mocks.loadCatalogMock,
        installModel: mocks.installModelMock,
        getInstallJob: mocks.getInstallJobMock,
        listCliDependencies: mocks.listCliDependenciesMock,
        installCliDependency: mocks.installCliDependencyMock,
        getCliDependencyInstallJob: mocks.getCliDependencyInstallJobMock,
    }),
}));

vi.mock('../useProviderAuth', () => ({
    useProviderAuth: () => ({
        startCodexDeviceLogin: mocks.startCodexDeviceLoginMock,
        startClaudeLogin: mocks.startClaudeLoginMock,
        fetchCliAuthStatus: mocks.fetchCliAuthStatusMock,
        cliLogout: mocks.cliLogoutMock,
    }),
}));

import { useProviders } from '../useProviders';

describe('useProviders', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('does not retry the removed legacy /ui/providers endpoint when canonical provider loading fails', async () => {
        mocks.fetchWithRetryMock
            .mockResolvedValueOnce({ ok: false })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

        const { result } = renderHook(() => useProviders());

        await act(async () => {
            await result.current.loadProviders();
        });

        const calledUrls = mocks.fetchWithRetryMock.mock.calls.map(([url]) => String(url));

        expect(calledUrls).toContain('http://127.0.0.1:9325/ops/provider');
        expect(calledUrls).toContain('http://127.0.0.1:9325/ui/nodes');
        expect(calledUrls.some((url) => url.includes('/ui/providers'))).toBe(false);
    });
});
