import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { useSecurityService } from '../useSecurityService'

describe('useSecurityService', () => {
    const mockEvents = [
        { timestamp: '2026-01-30T10:00:00', type: 'auth_failure', reason: 'Invalid token', actor: 'system', resolved: false }
    ]

    beforeEach(() => {
        vi.mocked(fetch).mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ panic_mode: false, events: mockEvents })
        } as Response)
    })

    it('fetches security status on mount', async () => {
        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.lockdown).toBe(false)
            expect(result.current.events).toEqual(mockEvents)
        })
    })

    it('includes authorization header when token provided', async () => {
        renderHook(() => useSecurityService('test-token'))

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    headers: { Authorization: 'Bearer test-token' }
                })
            )
        })
    })

    it('detects lockdown from status 503', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false,
            status: 503
        } as Response)

        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.lockdown).toBe(true)
        })
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
            json: () => Promise.resolve({ panic_mode: true, events: mockEvents })
        } as Response)

        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.lockdown).toBe(true)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({})
        } as Response)

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ panic_mode: false, events: [] })
        } as Response)

        await act(async () => {
            await result.current.clearLockdown()
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/security/resolve?action=clear_panic'),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('handles clear lockdown error', async () => {
        const { result } = renderHook(() => useSecurityService())

        await waitFor(() => {
            expect(result.current.events.length).toBe(1)
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        await act(async () => {
            await result.current.clearLockdown()
        })

        expect(result.current.error).toBe('Failed to clear lockdown')
    })
})
