import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { useRepoService } from '../useRepoService'

describe('useRepoService', () => {
    const mockRepos = [
        { name: 'repo1', path: '/path/to/repo1' },
        { name: 'repo2', path: '/path/to/repo2' }
    ]

    beforeEach(() => {
        vi.mocked(fetch).mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ repos: mockRepos, active_repo: '/path/to/repo1' })
        } as Response)
    })

    it('fetches repos on mount', async () => {
        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.repos).toEqual(mockRepos)
            expect(result.current.activeRepo).toBe('/path/to/repo1')
        })
    })

    it('includes authorization header when token provided', async () => {
        renderHook(() => useRepoService('test-token'))

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    headers: { Authorization: 'Bearer test-token' }
                })
            )
        })
    })

    it('handles fetch error', async () => {
        vi.mocked(fetch).mockRejectedValueOnce(new Error('Network error'))

        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.error).toBe('Network error')
        })
    })

    it('handles non-ok response', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.error).toBe('Failed to fetch repositories')
        })
    })

    it('bootstraps a repository', async () => {
        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.repos.length).toBe(2)
        })

        // Mock success for bootstrap endpoint
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: () => Promise.resolve({})
        } as Response)

        await act(async () => {
            await result.current.bootstrap('/path/to/repo1')
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/repos/bootstrap?path='),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('handles bootstrap error', async () => {
        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.repos.length).toBe(2)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 500
        } as Response)

        await act(async () => {
            await result.current.bootstrap('/path/to/repo1')
        })

        expect(result.current.error).toBe('Failed to bootstrap repository')
    })

    it('selects a repository', async () => {
        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.repos.length).toBe(2)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({})
        } as Response)

        await act(async () => {
            await result.current.selectRepo('/path/to/repo2')
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/repos/select?path='),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('handles selectRepo error', async () => {
        const { result } = renderHook(() => useRepoService())

        await waitFor(() => {
            expect(result.current.repos.length).toBe(2)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        await act(async () => {
            await result.current.selectRepo('/path/to/repo2')
        })

        expect(result.current.error).toBe('Failed to select repository')
    })

})
