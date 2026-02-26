import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AuthMethodSelector } from '../AuthMethodSelector';

describe('AuthMethodSelector', () => {
    it('muestra opciones base y Cold Room cuando está habilitado', () => {
        render(
            <AuthMethodSelector
                canUseColdRoom
                paired={false}
                renewalNeeded={false}
                onSelect={vi.fn()}
            />,
        );

        expect(screen.getByText('Google SSO')).toBeInTheDocument();
        expect(screen.getByText('Token local')).toBeInTheDocument();
        expect(screen.getByText('Sala Limpia')).toBeInTheDocument();
    });

    it('envía cold-renew cuando hay renovación pendiente', () => {
        const onSelect = vi.fn();
        render(
            <AuthMethodSelector
                canUseColdRoom
                paired
                renewalNeeded
                onSelect={onSelect}
            />,
        );

        fireEvent.click(screen.getByText('Sala Limpia'));
        expect(onSelect).toHaveBeenCalledWith('cold-renew');
        expect(screen.getByText('Renovación')).toBeInTheDocument();
    });

    it('muestra badges de estado activo y VM detectada', () => {
        const onSelect = vi.fn();
        render(
            <AuthMethodSelector
                canUseColdRoom
                paired
                renewalNeeded={false}
                vmDetected
                onSelect={onSelect}
            />,
        );

        expect(screen.getByText('Activa')).toBeInTheDocument();
        expect(screen.getByText('VM detectada')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Sala Limpia'));
        expect(onSelect).toHaveBeenCalledWith('cold-activate');
    });
});
