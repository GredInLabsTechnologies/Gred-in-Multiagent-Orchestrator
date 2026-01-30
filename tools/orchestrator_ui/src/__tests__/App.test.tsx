import { describe, it, expect, vi } from 'vitest'

import { render, screen } from '@testing-library/react'
import App from '../App'

// Mock MaintenanceIsland
vi.mock('../islands/system/MaintenanceIsland', () => ({
    MaintenanceIsland: () => <div data-testid="maintenance-island">MaintenanceIsland Mock</div>
}))

describe('App', () => {
    it('renders header with title', () => {
        render(<App />)
        expect(screen.getByText('Repo Orchestrator')).toBeInTheDocument()
    })

    it('renders company name', () => {
        render(<App />)
        expect(screen.getByText('Gred In Labs')).toBeInTheDocument()
    })

    it('renders footer with version', () => {
        render(<App />)
        expect(screen.getByText('v1.0.0')).toBeInTheDocument()
    })

    it('renders MaintenanceIsland component', () => {
        render(<App />)
        expect(screen.getByTestId('maintenance-island')).toBeInTheDocument()
    })

    it('has correct structure with header, main, and footer', () => {
        render(<App />)

        const header = screen.getByRole('banner')
        const main = screen.getByRole('main')
        const footer = screen.getByRole('contentinfo')

        expect(header).toBeInTheDocument()
        expect(main).toBeInTheDocument()
        expect(footer).toBeInTheDocument()
    })

    it('applies dark mode classes', () => {
        const { container } = render(<App />)
        const rootDiv = container.firstChild as HTMLElement

        expect(rootDiv).toHaveClass('min-h-screen')
        expect(rootDiv).toHaveClass('dark:bg-[#1d1d1f]')
    })
})
