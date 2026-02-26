import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ColdRoomActivatePanel } from '../ColdRoomActivatePanel';

describe('ColdRoomActivatePanel', () => {
    it('deshabilita activar cuando el blob es demasiado corto', () => {
        render(
            <ColdRoomActivatePanel
                machineId="GIMO-ABCD-1234"
                loading={false}
                onActivate={vi.fn(async () => undefined)}
            />,
        );

        const activateBtn = screen.getByRole('button', { name: /activar licencia cold room/i });
        expect(activateBtn).toBeDisabled();

        fireEvent.change(screen.getByPlaceholderText(/license blob firmado/i), {
            target: { value: 'short-blob' },
        });

        expect(activateBtn).toBeDisabled();
    });

    it('envía el blob recortado cuando es válido', async () => {
        const onActivate = vi.fn(async () => undefined);
        render(
            <ColdRoomActivatePanel
                machineId="GIMO-ABCD-1234"
                loading={false}
                onActivate={onActivate}
            />,
        );

        fireEvent.change(screen.getByPlaceholderText(/license blob firmado/i), {
            target: { value: '   this-is-a-valid-license-blob-value-123456   ' },
        });

        const activateBtn = screen.getByRole('button', { name: /activar licencia cold room/i });
        expect(activateBtn).toBeEnabled();

        fireEvent.click(activateBtn);

        expect(onActivate).toHaveBeenCalledWith('this-is-a-valid-license-blob-value-123456');
    });
});