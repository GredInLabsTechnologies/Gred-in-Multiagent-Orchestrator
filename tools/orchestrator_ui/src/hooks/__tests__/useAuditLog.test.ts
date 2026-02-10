import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { useAuditLog } from '../useAuditLog'


describe('useAuditLog', () => {
    const mockLogs = ['2026-01-30 READ file.txt', '2026-01-30 DENIED access', '2026-01-30 SYSTEM startup']

    beforeEach(() => {
        vi.mocked(fetch).mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ lines: mockLogs })
        } as Response)
    })

    it('fetches logs on mount', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs).toEqual(mockLogs)
        })
        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('/ui/audit?limit=200'),
            expect.any(Object)
        )
    })

    it('includes authorization header when token provided', async () => {
        renderHook(() => useAuditLog('test-token'))

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    headers: { Authorization: 'Bearer test-token' }
                })
            )
        })
    })

    it('uses custom limit parameter', async () => {
        renderHook(() => useAuditLog(undefined, 50))

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/ui/audit?limit=50'),
                expect.any(Object)
            )
        })
    })

    it('filters logs by read type', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs.length).toBe(3)
        })

        act(() => {
            result.current.setFilter('read')
        })

        expect(result.current.logs).toHaveLength(1)
        expect(result.current.logs[0]).toContain('READ')
    })

    it('filters logs by deny type', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs.length).toBe(3)
        })

        act(() => {
            result.current.setFilter('deny')
        })

        expect(result.current.logs).toHaveLength(1)
        expect(result.current.logs[0]).toContain('DENIED')
    })

    it('filters logs by system type (excludes read)', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs.length).toBe(3)
        })

        act(() => {
            result.current.setFilter('system')
        })

        expect(result.current.logs).toHaveLength(2)
        expect(result.current.logs.every(l => !l.toLowerCase().includes('read'))).toBe(true)
    })

    it('filters logs by search term', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs.length).toBe(3)
        })

        act(() => {
            result.current.setSearchTerm('file')
        })

        expect(result.current.logs).toHaveLength(1)
        expect(result.current.logs[0]).toContain('file')
    })

    it('handles fetch error', async () => {
        vi.mocked(fetch).mockRejectedValueOnce(new Error('Network error'))

        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.error).toBe('Network error')
        })
    })

    it('handles non-ok response', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: false
        } as Response)

        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.error).toBe('Failed to fetch audit logs')
        })
    })


    it('can manually refresh logs', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.rawLogs).toHaveLength(3)
        })

        const initialCalls = vi.mocked(fetch).mock.calls.length

        await act(async () => {
            await result.current.refresh()
        })

        expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(initialCalls)
    })

    it('reverses logs order (latest first)', async () => {
        const { result } = renderHook(() => useAuditLog())

        await waitFor(() => {
            expect(result.current.logs[0]).toContain('SYSTEM')
            expect(result.current.logs[2]).toContain('READ')
        })
    })
})
