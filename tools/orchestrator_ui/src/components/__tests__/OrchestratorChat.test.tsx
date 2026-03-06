import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OrchestratorChat } from '../OrchestratorChat';
import { describe, beforeEach, it, expect, vi } from 'vitest';

const addToastMock = vi.fn();

vi.mock('../Toast', () => ({
    useToast: () => ({ addToast: addToastMock }),
}));

describe('OrchestratorChat', () => {
    const chatInputPlaceholder = 'Describe el workflow o usa /comando...';

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('muestra intención detectada y estado por pasos al generar draft', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({
                ok: true,
                json: async () => [], // GET /ops/drafts on mount
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    id: 'd-help',
                    prompt: 'help',
                    provider: 'cognitive_direct_response',
                    content: 'Puedo ayudarte con un plan.',
                    status: 'draft',
                    context: {
                        detected_intent: 'HELP',
                        decision_path: 'direct_response',
                        can_bypass_llm: true,
                    },
                    created_at: '2026-02-19T12:00:00Z',
                }),
            });

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: 'help' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        await waitFor(() => {
            expect(screen.getByText('Intent: HELP')).toBeTruthy();
            expect(screen.getByText('Ruta: direct_response')).toBeTruthy();
            expect(screen.getByText(/Intencion detectada: HELP/)).toBeTruthy();
            expect(screen.getByText(/Draft creado: d-help/)).toBeTruthy();
        });
    });

    it('ejecuta flujo chat -> draft -> approve -> run desde UI', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({
                ok: true,
                json: async () => [], // GET /ops/drafts on mount
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    id: 'd-1',
                    prompt: 'crear plan de pruebas',
                    provider: 'cognitive_direct_response',
                    content: 'draft content',
                    status: 'draft',
                    context: {
                        detected_intent: 'CREATE_PLAN',
                        decision_path: 'direct_response',
                        can_bypass_llm: true,
                    },
                    created_at: '2026-02-19T12:00:00Z',
                }),
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    approved: {
                        id: 'a-1',
                        draft_id: 'd-1',
                        prompt: 'crear plan de pruebas',
                        provider: 'cognitive_direct_response',
                        content: 'draft content',
                        approved_at: '2026-02-19T12:01:00Z',
                        approved_by: 'admin:hash',
                    },
                    run: null,
                }),
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    id: 'r-1',
                    approved_id: 'a-1',
                    status: 'pending',
                    log: [],
                    created_at: '2026-02-19T12:02:00Z',
                }),
            });

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: 'crear plan de pruebas' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        const approveButtons = await screen.findAllByRole('button', { name: /aprobar/i });
        fireEvent.click(approveButtons[0]);

        const runButton = await screen.findByRole('button', { name: /ejecutar run/i });
        fireEvent.click(runButton);

        await waitFor(() => {
            expect(screen.getByText(/Run r-1 iniciado para approved a-1/)).toBeTruthy();
            expect(fetchMock).toHaveBeenCalledWith(
                expect.stringContaining('/ops/drafts'),
                expect.objectContaining({ credentials: 'include' }),
            );
            expect(fetchMock).toHaveBeenCalledWith(
                expect.stringContaining('/ops/runs'),
                expect.objectContaining({ method: 'POST' })
            );
        });
    });

    it('slash válido enruta a execute de skills sin pasar por generate', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => [] }) // /ops/drafts
            .mockResolvedValueOnce({ // /ops/skills (mount)
                ok: true,
                json: async () => ([
                    {
                        id: 'skill-1',
                        name: 'Explorar repo',
                        description: 'Explora estructura',
                        command: '/explorar',
                        replace_graph: false,
                        nodes: [],
                        edges: [],
                        created_at: '2026-03-05T00:00:00Z',
                        updated_at: '2026-03-05T00:00:00Z',
                    },
                ]),
            })
            .mockResolvedValueOnce({ // /ops/skills/{id}/execute
                ok: true,
                json: async () => ({
                    skill_run_id: 'skill_run_1',
                    skill_id: 'skill-1',
                    replace_graph: false,
                    status: 'queued',
                }),
            });

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat providerConnected={false} />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: '/explorar' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledWith(
                expect.stringContaining('/ops/skills/skill-1/execute'),
                expect.objectContaining({ method: 'POST' }),
            );
            expect(screen.getByText(/Skill \/explorar en cola/)).toBeTruthy();
        });

        expect(fetchMock).not.toHaveBeenCalledWith(
            expect.stringContaining('/ops/generate'),
            expect.anything(),
        );
    });

    it('slash inválido muestra feedback con sugerencia', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => [] }) // /ops/drafts
            .mockResolvedValueOnce({ // /ops/skills
                ok: true,
                json: async () => ([
                    {
                        id: 'skill-1',
                        name: 'Explorar repo',
                        description: 'Explora estructura',
                        command: '/explorar',
                        replace_graph: false,
                        nodes: [],
                        edges: [],
                        created_at: '2026-03-05T00:00:00Z',
                        updated_at: '2026-03-05T00:00:00Z',
                    },
                ]),
            });

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: '/desconocido' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        await waitFor(() => {
            expect(screen.getByText(/Comando \/desconocido no encontrado/)).toBeTruthy();
        });
    });

    it('permite enviar mensaje al terminal cuando existe callback', async () => {
        const onSendToTerminal = vi.fn();
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => [] }) // /ops/drafts
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    id: 'd-send-1',
                    prompt: 'hola terminal',
                    provider: 'cognitive_direct_response',
                    content: 'contenido para terminal',
                    status: 'draft',
                    context: { detected_intent: 'HELP', decision_path: 'direct_response', can_bypass_llm: true },
                    created_at: '2026-02-19T12:00:00Z',
                }),
            })
            .mockResolvedValue({ ok: true, json: async () => [] }); // /ops/skills mount

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat onSendToTerminal={onSendToTerminal} />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: 'hola terminal' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        const sendButtons = await screen.findAllByRole('button', { name: /enviar a terminal/i });
        fireEvent.click(sendButtons[0]);

        expect(onSendToTerminal).toHaveBeenCalled();
        expect(onSendToTerminal.mock.calls[0][0]).toEqual(
            expect.objectContaining({
                source: 'chat',
            }),
        );
    });

    it('muestra resumen entrante desde terminal', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({ ok: true, json: async () => [] }) // /ops/drafts
            .mockResolvedValue({ ok: true, json: async () => [] }); // /ops/skills mount

        vi.stubGlobal('fetch', fetchMock);

        const inbound = {
            id: 'sum-1',
            text: 'resumen desde terminal',
            ts: '2026-02-19T12:00:00Z',
        };

        render(<OrchestratorChat inboundTerminalSummary={inbound} />);

        await waitFor(() => {
            expect(screen.getByText(/\[Terminal\] resumen desde terminal/)).toBeTruthy();
        });
    });

    it('muestra tabs de drafts por estado con conteos', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ([
                    { id: 'd-a', prompt: 'pendiente', status: 'draft', created_at: '2026-02-19T12:00:00Z' },
                    { id: 'd-b', prompt: 'aprobado', status: 'approved', created_at: '2026-02-19T11:59:00Z' },
                    { id: 'd-c', prompt: 'rechazado', status: 'rejected', created_at: '2026-02-19T11:58:00Z' },
                ]),
            })
            .mockResolvedValueOnce({ ok: true, json: async () => [] }); // /ops/skills mount

        vi.stubGlobal('fetch', fetchMock);

        render(<OrchestratorChat />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Pendientes \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Aprobados \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Rech\/Error \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Todos \(3\)/i })).toBeTruthy();
        });
    });
});
