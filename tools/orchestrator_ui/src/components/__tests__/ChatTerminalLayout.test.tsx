import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, beforeEach, it, expect, vi } from 'vitest';
import { ChatTerminalLayout } from '../ChatTerminalLayout';

vi.mock('../OrchestratorChat', () => ({
    OrchestratorChat: ({ onSendToTerminal, inboundTerminalSummary }: any) => (
        <div data-testid="mock-chat">
            <button
                onClick={() => onSendToTerminal?.({ text: 'from-chat', ts: '2026-03-01T10:00:00Z', source: 'chat' })}
            >
                chat-send-terminal
            </button>
            <div>{inboundTerminalSummary ? `summary:${inboundTerminalSummary.text}` : 'summary:none'}</div>
        </div>
    ),
}));

vi.mock('../OpsTerminal', () => ({
    OpsTerminal: ({ inboundFromChat, onSendSummaryToChat }: any) => (
        <div data-testid="mock-terminal">
            <button
                onClick={() => onSendSummaryToChat?.({ id: 'sum-1', text: 'from-terminal', ts: '2026-03-01T10:01:00Z' })}
            >
                terminal-send-summary
            </button>
            <div>{inboundFromChat ? `inbound:${inboundFromChat.text}` : 'inbound:none'}</div>
        </div>
    ),
}));

describe('ChatTerminalLayout', () => {
    beforeEach(() => {
        localStorage.clear();
        vi.clearAllMocks();
    });

    it('muestra tabs por defecto y renderiza chat inicialmente', () => {
        render(<ChatTerminalLayout providerConnected />);

        expect(screen.getByRole('button', { name: /💬 Chat/i })).toBeTruthy();
        expect(screen.getByRole('button', { name: />_ Terminal/i })).toBeTruthy();
        expect(screen.getByTestId('mock-chat')).toBeTruthy();
    });

    it('cambia a terminal con click izquierdo', () => {
        render(<ChatTerminalLayout providerConnected />);

        fireEvent.click(screen.getByRole('button', { name: />_ Terminal/i }));

        expect(screen.getByTestId('mock-terminal')).toBeTruthy();
    });

    it('abre menú contextual y permite pasar a modo dividido', async () => {
        render(<ChatTerminalLayout providerConnected />);

        fireEvent.contextMenu(screen.getByRole('button', { name: />_ Terminal/i }));
        fireEvent.click(screen.getByRole('button', { name: /Modo Dividido/i }));

        await waitFor(() => {
            expect(screen.getAllByTestId('mock-chat').length).toBeGreaterThan(0);
            expect(screen.getAllByTestId('mock-terminal').length).toBeGreaterThan(0);
        });
    });

    it('cierra menú contextual con Escape', () => {
        render(<ChatTerminalLayout providerConnected />);

        fireEvent.contextMenu(screen.getByRole('button', { name: />_ Terminal/i }));
        expect(screen.getByRole('menu')).toBeTruthy();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(screen.queryByRole('menu')).toBeNull();
    });

    it('persiste activeTab y viewMode en localStorage', () => {
        render(<ChatTerminalLayout providerConnected />);

        fireEvent.click(screen.getByRole('button', { name: />_ Terminal/i }));
        fireEvent.contextMenu(screen.getByRole('button', { name: />_ Terminal/i }));
        fireEvent.click(screen.getByRole('button', { name: /Modo Dividido/i }));

        expect(localStorage.getItem('orchestrator.chat_terminal.active_tab')).toBe('terminal');
        expect(localStorage.getItem('orchestrator.chat_terminal.view_mode')).toBe('split');
    });

    it('propaga interacciones chat↔terminal en modo dividido', async () => {
        render(<ChatTerminalLayout providerConnected />);

        fireEvent.contextMenu(screen.getByRole('button', { name: />_ Terminal/i }));
        fireEvent.click(screen.getByRole('button', { name: /Modo Dividido/i }));

        fireEvent.click(screen.getAllByText('chat-send-terminal')[0]);
        await waitFor(() => {
            expect(screen.getAllByText('inbound:from-chat').length).toBeGreaterThan(0);
        });

        fireEvent.click(screen.getAllByText('terminal-send-summary')[0]);
        await waitFor(() => {
            expect(screen.getAllByText('summary:from-terminal').length).toBeGreaterThan(0);
        });
    });
});
