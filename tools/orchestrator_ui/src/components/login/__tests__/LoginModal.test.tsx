import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LoginModal } from '../../LoginModal';

const addToastMock = vi.fn();
const refreshColdStatusMock = vi.fn(async () => undefined);

let mockedColdStatus: any = {
    enabled: true,
    paired: false,
    renewal_needed: false,
    vm_detected: false,
    machine_id: 'GIMO-TEST-0001',
};

vi.mock('../../Toast', () => ({
    useToast: () => ({ addToast: addToastMock }),
}));

vi.mock('../../../hooks/useColdRoomStatus', () => ({
    useColdRoomStatus: () => ({
        status: mockedColdStatus,
        loading: false,
        refresh: refreshColdStatusMock,
    }),
}));

vi.mock('../../../lib/firebase', () => ({
    auth: null,
    googleProvider: null,
    isFirebaseConfigured: () => false,
}));

describe('LoginModal (Cold Room)', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.clearAllMocks();

        mockedColdStatus = {
            enabled: true,
            paired: false,
            renewal_needed: false,
            vm_detected: false,
            machine_id: 'GIMO-TEST-0001',
        };

        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: vi.fn().mockImplementation(() => ({
                matches: true,
                media: '(prefers-reduced-motion: reduce)',
                onchange: null,
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                addListener: vi.fn(),
                removeListener: vi.fn(),
                dispatchEvent: vi.fn(),
            })),
        });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('mapea invalid_signature en activación cold-room', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'invalid_signature' }),
            }),
        );

        render(<LoginModal onAuthenticated={vi.fn()} />);

        fireEvent.click(await screen.findByText('Sala Limpia'));

        fireEvent.change(screen.getByPlaceholderText(/license blob firmado/i), {
            target: { value: 'blob-valid-en-longitud-123456789' },
        });

        fireEvent.click(screen.getByRole('button', { name: /activar licencia cold room/i }));

        await waitFor(() => {
            expect(screen.getByText(/firma inválida/i)).toBeInTheDocument();
        });
    });

    it('renueva cold-room y completa autenticación en éxito', async () => {
        const onAuthenticated = vi.fn();

        mockedColdStatus = {
            enabled: true,
            paired: true,
            renewal_needed: true,
            vm_detected: false,
            machine_id: 'GIMO-TEST-0001',
            plan: 'enterprise_cold_room',
            features: ['orchestration'],
            renewals_remaining: 3,
            days_remaining: 1,
            expires_at: '2026-03-01T00:00:00Z',
        };

        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: true,
                json: async () => ({}),
            }),
        );

        render(<LoginModal onAuthenticated={onAuthenticated} />);

        fireEvent.click(await screen.findByText('Sala Limpia'));

        fireEvent.change(screen.getByPlaceholderText(/nuevo license blob firmado/i), {
            target: { value: 'renewal-blob-valid-abcdefghijklmnopqrstuvwxyz' },
        });

        fireEvent.click(screen.getByRole('button', { name: /renovar licencia cold room/i }));

        await waitFor(() => {
            expect(addToastMock).toHaveBeenCalledWith('Renovación Cold Room aplicada', 'success');
        });

        vi.advanceTimersByTime(500);
        expect(onAuthenticated).toHaveBeenCalled();
    });
});