import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { useSystemService } from '../useSystemService'

describe('useSystemService', () => {
    beforeEach(() => {
        vi.mocked(fetch).mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ status: 'RUNNING' })
        } as Response)
    })

    it('fetches status on mount', async () => {
        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.status).toBe('RUNNING')
        })
    })

    it('starts with UNKNOWN status', () => {
        vi.mocked(fetch).mockReturnValue(new Promise(() => { }))
        const { result } = renderHook(() => useSystemService())
        expect(result.current.status).toBe('UNKNOWN')
    })

    it('includes authorization header when token provided', async () => {
        renderHook(() => useSystemService('test-token'))

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

        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.error).toBe('Network error')
        })
    })

    it('handles non-ok response', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.error).toBe('Failed to fetch service status')
        })
    })

    it('restarts service', async () => {
        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.status).toBe('RUNNING')
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({})
        } as Response)

        await act(async () => {
            await result.current.restart()
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/service/restart'),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('stops service', async () => {
        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.status).toBe('RUNNING')
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({})
        } as Response)

        await act(async () => {
            await result.current.stop()
        })

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/service/stop'),
            expect.objectContaining({ method: 'POST' })
        )
    })

    it('handles restart error', async () => {
        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.status).toBe('RUNNING')
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        await act(async () => {
            await result.current.restart()
        })

        expect(result.current.error).toBe('Failed to restart service')
    })

    it('handles stop error', async () => {
        const { result } = renderHook(() => useSystemService())

        await waitFor(() => {
            expect(result.current.status).toBe('RUNNING')
        })

        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        await act(async () => {
            await result.current.stop()
        })

        expect(result.current.error).toBe('Failed to stop service')
    })

})
