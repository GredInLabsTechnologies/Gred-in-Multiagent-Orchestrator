import { describe, it, expect, vi } from 'vitest'

import { render, screen, fireEvent } from '@testing-library/react'
import { Accordion, SettingsSlider } from '../Accordion'

describe('Accordion', () => {
    it('renders title', () => {
        render(
            <Accordion title="Test Section">
                <p>Content</p>
            </Accordion>
        )

        expect(screen.getByText('Test Section')).toBeInTheDocument()
    })

    it('is closed by default', () => {
        render(
            <Accordion title="Test Section">
                <p>Hidden Content</p>
            </Accordion>
        )

        const content = screen.getByText('Hidden Content').parentElement?.parentElement
        expect(content).toHaveClass('max-h-0')
        expect(content).toHaveClass('opacity-0')
    })

    it('opens when defaultOpen is true', () => {
        render(
            <Accordion title="Test Section" defaultOpen={true}>
                <p>Visible Content</p>
            </Accordion>
        )

        const content = screen.getByText('Visible Content').parentElement?.parentElement
        expect(content).toHaveClass('max-h-[500px]')
        expect(content).toHaveClass('opacity-100')
    })

    it('toggles open/close on click', () => {
        render(
            <Accordion title="Test Section">
                <p>Toggle Content</p>
            </Accordion>
        )

        const button = screen.getByRole('button')
        const content = screen.getByText('Toggle Content').parentElement?.parentElement

        // Initially closed
        expect(content).toHaveClass('max-h-0')

        // Click to open
        fireEvent.click(button)
        expect(content).toHaveClass('max-h-[500px]')

        // Click to close
        fireEvent.click(button)
        expect(content).toHaveClass('max-h-0')
    })

    it('displays badge when provided', () => {
        render(
            <Accordion title="Test Section" badge="NEW">
                <p>Content</p>
            </Accordion>
        )

        expect(screen.getByText('NEW')).toBeInTheDocument()
    })

    it('does not display badge when not provided', () => {
        render(
            <Accordion title="Test Section">
                <p>Content</p>
            </Accordion>
        )

        expect(screen.queryByText('NEW')).not.toBeInTheDocument()
    })

    it('renders children correctly', () => {
        render(
            <Accordion title="Test Section">
                <p data-testid="child-1">Child 1</p>
                <p data-testid="child-2">Child 2</p>
            </Accordion>
        )

        expect(screen.getByTestId('child-1')).toBeInTheDocument()
        expect(screen.getByTestId('child-2')).toBeInTheDocument()
    })

    it('rotates chevron icon when open', () => {
        render(
            <Accordion title="Test Section">
                <p>Content</p>
            </Accordion>
        )

        const button = screen.getByRole('button')
        const chevron = button.querySelector('svg')

        expect(chevron).not.toHaveClass('rotate-180')

        fireEvent.click(button)
        expect(chevron).toHaveClass('rotate-180')
    })
})

describe('SettingsSlider', () => {
    it('renders label and value', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Volume" value={50} onChange={onChange} />
        )

        expect(screen.getByText('Volume')).toBeInTheDocument()
        expect(screen.getByText('50%')).toBeInTheDocument()
    })

    it('calls onChange when slider moves', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Volume" value={50} onChange={onChange} />
        )

        const slider = screen.getByRole('slider')
        fireEvent.change(slider, { target: { value: '75' } })

        expect(onChange).toHaveBeenCalledWith(75)
    })

    it('uses custom min and max values', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Temperature" value={25} onChange={onChange} min={10} max={40} unit="°C" />
        )

        expect(screen.getByText('10°C')).toBeInTheDocument()
        expect(screen.getByText('40°C')).toBeInTheDocument()
        expect(screen.getByText('25°C')).toBeInTheDocument()
    })

    it('uses custom unit', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Speed" value={100} onChange={onChange} unit="km/h" />
        )

        // Value and max both show 100km/h, so use getAllByText
        const elements = screen.getAllByText('100km/h')
        expect(elements.length).toBeGreaterThanOrEqual(1)
    })

    it('calculates progress bar width correctly', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Progress" value={50} onChange={onChange} min={0} max={100} />
        )

        // With value=50, min=0, max=100, width should be 50%
        const progressBar = document.querySelector('[style*="width"]')
        expect(progressBar).toHaveStyle({ width: '50%' })
    })

    it('calculates progress with non-zero min', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Range" value={30} onChange={onChange} min={20} max={40} />
        )

        // With value=30, min=20, max=40, width should be (30-20)/(40-20)*100 = 50%
        const progressBar = document.querySelector('[style*="width"]')
        expect(progressBar).toHaveStyle({ width: '50%' })
    })

    it('uses default values for optional props', () => {
        const onChange = vi.fn()
        render(
            <SettingsSlider label="Default" value={25} onChange={onChange} />
        )

        const slider = screen.getByRole('slider')
        expect(slider).toHaveAttribute('min', '0')
        expect(slider).toHaveAttribute('max', '100')
        expect(screen.getByText('0%')).toBeInTheDocument()
        expect(screen.getByText('100%')).toBeInTheDocument()
    })
})
