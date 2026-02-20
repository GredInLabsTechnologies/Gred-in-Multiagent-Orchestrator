import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MaintenanceIsland } from '../islands/system/MaintenanceIsland'

// Mock all hooks
vi.mock('../hooks/useSystemService', () => ({
    useSystemService: vi.fn()
}))

vi.mock('../hooks/useAuditLog', () => ({
    useAuditLog: vi.fn()
}))

vi.mock('../hooks/useSecurityService', () => ({
    useSecurityService: vi.fn()
}))

vi.mock('../hooks/useRepoService', () => ({
    useRepoService: vi.fn()
}))

import { useSystemService } from '../hooks/useSystemService'
import { useAuditLog } from '../hooks/useAuditLog'
import { useSecurityService } from '../hooks/useSecurityService'
import { useRepoService } from '../hooks/useRepoService'
import type { ServiceStatus } from '../hooks/useSystemService'

describe('MaintenanceIsland', () => {
    const mockSystemService = {
        status: 'RUNNING' as const,
        isLoading: false,
        error: null,
        restart: vi.fn(),
        stop: vi.fn(),
        refresh: vi.fn()
    }

    const mockAuditLog = {
        logs: ['2026-01-30 READ file.txt', '2026-01-30 DENIED access'],
        rawLogs: ['2026-01-30 READ file.txt', '2026-01-30 DENIED access'],
        error: null,
        filter: 'all' as const,
        setFilter: vi.fn(),
        searchTerm: '',
        setSearchTerm: vi.fn(),
        refresh: vi.fn()
    }

    const mockSecurityService = {
        threatLevel: 0,
        threatLevelLabel: 'NOMINAL',
        autoDecayRemaining: null,
        activeSources: 0,
        lockdown: false,
        trustDashboard: [],
        isLoading: false,
        error: null,
        clearLockdown: vi.fn(),
        resetThreats: vi.fn(),
        downgrade: vi.fn(),
        refresh: vi.fn()
        ,
        fetchTrustDashboard: vi.fn(),
        getCircuitBreakerConfig: vi.fn().mockResolvedValue(null)
    }

    const mockRepoService = {
        repos: [
            { name: 'repo1', path: '/path/to/repo1' },
            { name: 'repo2', path: '/path/to/repo2' }
        ],
        activeRepo: '/path/to/repo1',
        isLoading: false,
        error: null,
        bootstrap: vi.fn(),
        selectRepo: vi.fn(),
        refresh: vi.fn()
    }

    const setLockdown = (lockdown: boolean, extras: Record<string, unknown> = {}) => {
        vi.mocked(useSecurityService).mockReturnValue({
            ...mockSecurityService,
            threatLevel: lockdown ? 3 : 0,
            threatLevelLabel: lockdown ? 'LOCKDOWN' : 'NOMINAL',
            lockdown,
            ...extras
        })
    }

    const mockEmptyLogs = () => {
        vi.mocked(useAuditLog).mockReturnValue({
            ...mockAuditLog,
            logs: [],
            rawLogs: []
        })
    }

    beforeEach(() => {
        vi.mocked(useSystemService).mockReturnValue(mockSystemService)
        vi.mocked(useAuditLog).mockReturnValue(mockAuditLog)
        vi.mocked(useSecurityService).mockReturnValue(mockSecurityService)
        vi.mocked(useRepoService).mockReturnValue(mockRepoService)
    })

    it('renders service status', () => {
        render(<MaintenanceIsland />)
        expect(screen.getByText('RUNNING')).toBeInTheDocument()
    })

    it('renders system status label', () => {
        render(<MaintenanceIsland />)
        // "Status" appears as a heading label in the system core card
        const statusElements = screen.getAllByText('Status')
        expect(statusElements.length).toBeGreaterThanOrEqual(1)
    })

    it('calls restart when restart button clicked', () => {
        render(<MaintenanceIsland />)
        const restartButton = screen.getByTitle('Restart Service')
        fireEvent.click(restartButton)
        expect(mockSystemService.restart).toHaveBeenCalled()
    })

    it('calls stop when stop button clicked', () => {
        render(<MaintenanceIsland />)
        const stopButton = screen.getByTitle('Stop Service')
        fireEvent.click(stopButton)
        expect(mockSystemService.stop).toHaveBeenCalled()
    })

    it('disables stop button when status is STOPPED', () => {
        vi.mocked(useSystemService).mockReturnValue({
            ...mockSystemService,
            status: 'STOPPED'
        })
        render(<MaintenanceIsland />)
        const stopButton = screen.getByTitle('Stop Service')
        expect(stopButton).toBeDisabled()
    })

    it('shows error message when serviceError exists', () => {
        vi.mocked(useSystemService).mockReturnValue({
            ...mockSystemService,
            error: 'Service unavailable'
        })
        render(<MaintenanceIsland />)
        expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    })

    it('renders lockdown status when lockdown is true', () => {
        setLockdown(true)
        render(<MaintenanceIsland />)
        // LOCKDOWN appears in both status and security level sections
        const lockdownElements = screen.getAllByText('LOCKDOWN')
        expect(lockdownElements.length).toBeGreaterThanOrEqual(1)
    })

    it('calls clearLockdown when reset button clicked', () => {
        setLockdown(true)
        render(<MaintenanceIsland />)
        const resetButton = screen.getByTitle('Reset to NOMINAL')
        fireEvent.click(resetButton)
        expect(mockSecurityService.clearLockdown).toHaveBeenCalled()
    })

    it('displays LOCKDOWN as status label when in lockdown', () => {
        setLockdown(true)
        render(<MaintenanceIsland />)
        const lockdownElements = screen.getAllByText('LOCKDOWN')
        expect(lockdownElements.length).toBeGreaterThanOrEqual(1)
    })

    it('renders repository dropdown with repos', () => {
        render(<MaintenanceIsland />)
        const select = screen.getByLabelText('Target Repository')
        expect(select).toBeInTheDocument()
        // Check options exist
        const options = select.querySelectorAll('option')
        expect(options.length).toBeGreaterThanOrEqual(2)
    })

    it('shows active repo', () => {
        render(<MaintenanceIsland />)
        // Active repo is shown - may appear multiple times (dropdown + display)
        const elements = screen.getAllByText(/\/path\/to\/repo1/)
        expect(elements.length).toBeGreaterThanOrEqual(1)
    })


    it('calls bootstrap when Bootstrap button clicked', () => {
        render(<MaintenanceIsland />)

        // Select a repo first
        const select = screen.getByLabelText('Target Repository')
        fireEvent.change(select, { target: { value: '/path/to/repo1' } })

        const bootstrapButton = screen.getByText('Bootstrap files')
        fireEvent.click(bootstrapButton)
        expect(mockRepoService.bootstrap).toHaveBeenCalledWith('/path/to/repo1')
    })

    it('calls selectRepo when Activate button clicked', () => {
        render(<MaintenanceIsland />)

        // Select a different repo
        const select = screen.getByLabelText('Target Repository')
        fireEvent.change(select, { target: { value: '/path/to/repo2' } })

        const activateButton = screen.getByText('Activate')
        fireEvent.click(activateButton)
        expect(mockRepoService.selectRepo).toHaveBeenCalledWith('/path/to/repo2')
    })

    it('renders audit logs', () => {
        render(<MaintenanceIsland />)
        expect(screen.getByText('2026-01-30 READ file.txt')).toBeInTheDocument()
        expect(screen.getByText('2026-01-30 DENIED access')).toBeInTheDocument()
    })

    it('shows no matches message when logs empty', () => {
        mockEmptyLogs()
        render(<MaintenanceIsland />)
        expect(screen.getByText('No matching events')).toBeInTheDocument()
    })

    it('updates search term on input', () => {
        render(<MaintenanceIsland />)
        const searchInput = screen.getByPlaceholderText('Search logs...')
        fireEvent.change(searchInput, { target: { value: 'test' } })
        expect(mockAuditLog.setSearchTerm).toHaveBeenCalledWith('test')
    })

    it('updates filter on select change', () => {
        render(<MaintenanceIsland />)
        const filterSelect = screen.getByDisplayValue('ANY')
        fireEvent.change(filterSelect, { target: { value: 'deny' } })
        expect(mockAuditLog.setFilter).toHaveBeenCalledWith('deny')
    })

    it('calls refreshLogs when refresh button clicked', () => {
        render(<MaintenanceIsland />)
        const refreshButton = screen.getByTitle('Refresh Logs')
        fireEvent.click(refreshButton)
        expect(mockAuditLog.refresh).toHaveBeenCalled()
    })

    it('exports logs when export button clicked', () => {
        render(<MaintenanceIsland />)
        const exportButton = screen.getByTitle('Export Logs')
        fireEvent.click(exportButton)

        // Verify URL APIs were called (mocked in setup.ts)
        expect(URL.createObjectURL).toHaveBeenCalled()
        expect(URL.revokeObjectURL).toHaveBeenCalled()
    })

    it('applies correct class for DENIED logs', () => {
        render(<MaintenanceIsland />)
        const deniedLog = screen.getByText('2026-01-30 DENIED access')
        expect(deniedLog).toHaveClass('text-red-400')
    })

    it('applies correct class for READ logs', () => {
        render(<MaintenanceIsland />)
        const readLog = screen.getByText('2026-01-30 READ file.txt')
        expect(readLog).toHaveClass('text-blue-400')
    })

    it('shows NOMINAL security level when not in lockdown', () => {
        render(<MaintenanceIsland />)
        expect(screen.getByText('NOMINAL')).toBeInTheDocument()
    })

    it('shows LOCKDOWN security level when in lockdown', () => {
        setLockdown(true)
        render(<MaintenanceIsland />)
        expect(screen.getAllByText('LOCKDOWN').length).toBeGreaterThanOrEqual(1)
    })

    it('applies correct status colors for different statuses', () => {
        const statuses = [
            { id: 'RUNNING', label: 'RUNNING' },
            { id: 'STOPPED', label: 'STOPPED' },
            { id: 'STARTING', label: 'STARTING' },
            { id: 'STOPPING', label: 'STOPPING' },
            { id: 'UNKNOWN', label: 'UNKNOWN' }
        ] as const

        statuses.forEach(({ id, label }) => {
            vi.mocked(useSystemService).mockReturnValue({
                ...mockSystemService,
                status: id as ServiceStatus
            })
            const { unmount } = render(<MaintenanceIsland />)
            expect(screen.getByText(label)).toBeInTheDocument()
            unmount()
        })
    })

    it('disables buttons when isLoading', () => {
        vi.mocked(useSystemService).mockReturnValue({
            ...mockSystemService,
            isLoading: true
        })
        render(<MaintenanceIsland />)
        const restartButton = screen.getByTitle('Restart Service')
        const stopButton = screen.getByTitle('Stop Service')
        expect(restartButton).toBeDisabled()
        expect(stopButton).toBeDisabled()
    })

    it('disables buttons when in lockdown', () => {
        setLockdown(true)
        render(<MaintenanceIsland />)
        const restartButton = screen.getByTitle('Restart Service')
        const stopButton = screen.getByTitle('Stop Service')
        expect(restartButton).toBeDisabled()
        expect(stopButton).toBeDisabled()
    })

    it('disables reset button when security isLoading in lockdown', () => {
        setLockdown(true, { isLoading: true })
        render(<MaintenanceIsland />)
        const resetButton = screen.getByTitle('Reset to NOMINAL')
        expect(resetButton).toBeDisabled()
    })

    it('passes token to hooks', () => {
        render(<MaintenanceIsland token="my-token" />)
        expect(useSystemService).toHaveBeenCalledWith('my-token')
        expect(useAuditLog).toHaveBeenCalledWith('my-token')
        expect(useSecurityService).toHaveBeenCalledWith('my-token')
        expect(useRepoService).toHaveBeenCalledWith('my-token')
    })

    it('does not export when rawLogs is empty', () => {
        mockEmptyLogs()

        render(<MaintenanceIsland />)
        const exportButton = screen.getByTitle('Export Logs')

        // Clear URL mocks before clicking
        vi.mocked(URL.createObjectURL).mockClear()
        fireEvent.click(exportButton)


        // Should not call createObjectURL when logs are empty
        expect(URL.createObjectURL).not.toHaveBeenCalled()
    })

    it('applies correct class for SYSTEM logs', () => {
        vi.mocked(useAuditLog).mockReturnValue({
            ...mockAuditLog,
            logs: ['2026-01-30 SYSTEM initialization complete'],
            rawLogs: ['2026-01-30 SYSTEM initialization complete']
        })
        render(<MaintenanceIsland />)
        const systemLog = screen.getByText('2026-01-30 SYSTEM initialization complete')
        expect(systemLog).toHaveClass('text-amber-400')
    })

    it('applies default class for generic logs without keywords', () => {
        vi.mocked(useAuditLog).mockReturnValue({
            ...mockAuditLog,
            logs: ['2026-01-30 Some generic log message'],
            rawLogs: ['2026-01-30 Some generic log message']
        })
        render(<MaintenanceIsland />)
        const genericLog = screen.getByText('2026-01-30 Some generic log message')
        expect(genericLog).toHaveClass('text-zinc-400')
    })
})
