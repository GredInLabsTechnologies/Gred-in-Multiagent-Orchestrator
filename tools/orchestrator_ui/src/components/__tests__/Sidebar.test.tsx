import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import { useAppStore } from '../../stores/appStore';

describe('Sidebar', () => {
    it('renders primary tab buttons', () => {
        render(<Sidebar />);
        expect(screen.getByLabelText('Grafo')).toBeInTheDocument();
        expect(screen.getByLabelText('Planes')).toBeInTheDocument();
        expect(screen.getByLabelText('Ajustes')).toBeInTheDocument();
    });

    it('updates store when tab clicked', () => {
        render(<Sidebar />);
        fireEvent.click(screen.getByLabelText('Planes'));
        expect(useAppStore.getState().activeTab).toBe('plans');
    });

    it('opens settings overlay when gear clicked', () => {
        render(<Sidebar />);
        fireEvent.click(screen.getByLabelText('Ajustes'));
        expect(useAppStore.getState().activeOverlay).toBe('settings');
    });
});
