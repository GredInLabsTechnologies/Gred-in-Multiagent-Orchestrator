import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ColdRoomRenewalPanel } from '../ColdRoomRenewalPanel';

describe('ColdRoomRenewalPanel', () => {
    it('muestra el estado recibido y mantiene botón deshabilitado con blob corto', () => {
        render(
            <ColdRoomRenewalPanel
                expiresAt="2026-03-30T00:00:00Z"
                daysRemaining={12}
                plan="enterprise_cold_room"
                features={['orchestration', 'trust']}
                renewalsRemaining={3}
                loading={false}
                onRenew={vi.fn(async () => undefined)}
            />,
        );

        expect(screen.getByText('enterprise_cold_room')).toBeInTheDocument();
        expect(screen.getByText('12')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('orchestration, trust')).toBeInTheDocument();

        const renewBtn = screen.getByRole('button', { name: /renovar licencia cold room/i });
        expect(renewBtn).toBeDisabled();

        fireEvent.change(screen.getByPlaceholderText(/nuevo license blob firmado/i), {
            target: { value: 'tiny' },
        });

        expect(renewBtn).toBeDisabled();
    });

    it('envía el blob recortado al renovar', () => {
        const onRenew = vi.fn(async () => undefined);

        render(
            <ColdRoomRenewalPanel
                loading={false}
                onRenew={onRenew}
            />,
        );

        fireEvent.change(screen.getByPlaceholderText(/nuevo license blob firmado/i), {
            target: { value: '   renewal-valid-blob-abcdefghijklmnopqrstuvwxyz   ' },
        });

        const renewBtn = screen.getByRole('button', { name: /renovar licencia cold room/i });
        expect(renewBtn).toBeEnabled();

        fireEvent.click(renewBtn);

        expect(onRenew).toHaveBeenCalledWith('renewal-valid-blob-abcdefghijklmnopqrstuvwxyz');
    });
});