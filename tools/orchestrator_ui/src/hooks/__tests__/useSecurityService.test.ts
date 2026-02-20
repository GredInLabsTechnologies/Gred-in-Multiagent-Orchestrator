import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { useSecurityService } from '../useSecurityService'

describe('useSecurityService', () => {
    const mockSecurityData = {
        threat_level: 0,
        threat_level_label: 'NOMINAL',
        auto_decay_remaining: null,
        active_sources: 0,
        panic_mode: false,
        recent_events_count: 1
    }

    beforeEach(() => {
        vi.mocked(fetch).mockResolvedValue({
            ok: true,
            json: () => Promise.resolve(mockSecurityData)
        } as Response)
    })

    it('fetches security status on mount', async () => {
        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.lockdown).toBe(false)
            expect(result.current.threatLevel).toBe(0)
        })
    })

    it('usa sesión por cookies aunque se pase token', async () => {
        renderHook(() => useSecurityService('test-token'))

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    credentials: 'include'
                })
            )
        })
    })

    it('detects lockdown from status 503', async () => {
        // First call succeeds to establish state, then 503 triggers lockdown
        vi.mocked(fetch)
            .mockResolvedValueOnce({
                ok: true,
                json: () => Promise.resolve(mockSecurityData)
            } as Response)
            .mockResolvedValueOnce({
                ok: false,
                status: 503
            } as Response)

        const { result } = renderHook(() => useSecurityService())

        // Wait for initial fetch to establish state
        await waitFor(() => {
            expect(result.current.threatLevel).toBe(0)
        })

        // Trigger refresh which will get 503
        await act(async () => {
            await result.current.refresh()
        })

        expect(result.current.lockdown).toBe(true)
    })

    it('handles fetch error', async () => {
        vi.mocked(fetch).mockRejectedValueOnce(new Error('Network error'))

        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.error).toBe('Network error')
        })
    })

    it('handles non-ok non-503 response', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 500
        } as Response)

        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.error).toBe('Failed to fetch security status')
        })
    })

    it('clears lockdown', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ ...mockSecurityData, threat_level: 3, threat_level_label: 'LOCKDOWN', panic_mode: true })
        } as Response)

        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.lockdown).toBe(true)
        })

        // Mock the POST to /ops/trust/reset
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({})
        } as Response)

        // Mock the subsequent fetchStatus call
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ ...mockSecurityData, threat_level: 0, threat_level_label: 'NOMINAL', panic_mode: false })
        } as Response)

        await act(async () => {
            await result.current.clearLockdown()
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ops/trust/reset'),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('handles clear lockdown error', async () => {
        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.threatLevel).toBe(0)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            json: () => Promise.resolve({})
        } as unknown as Response)

        await act(async () => {
            await result.current.clearLockdown()
        })

        expect(result.current.error).toBe('Failed to clear_all security')
    })
})
