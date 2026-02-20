import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Sidebar } from '../Sidebar';

describe('Sidebar', () => {
    it('renders all tab buttons', () => {
        render(<Sidebar activeTab="graph" onTabChange={vi.fn()} />);
        expect(screen.getByTitle('Graph')).toBeInTheDocument();
        expect(screen.getByTitle('Maint')).toBeInTheDocument();
        expect(screen.getByTitle('Logs')).toBeInTheDocument();
        expect(screen.getByTitle('Settings')).toBeInTheDocument();
    });

    it('calls onTabChange when tab clicked', () => {
        const onTabChange = vi.fn();
        render(<Sidebar activeTab="graph" onTabChange={onTabChange} />);
        fireEvent.click(screen.getByTitle('Maint'));
        expect(onTabChange).toHaveBeenCalledWith('maintenance');
    });

    it('highlights active tab', () => {
        render(<Sidebar activeTab="logs" onTabChange={vi.fn()} />);
        const logsButton = screen.getByTitle('Logs');
        expect(logsButton.className).toContain('text-[#0a84ff]');
    });
});
