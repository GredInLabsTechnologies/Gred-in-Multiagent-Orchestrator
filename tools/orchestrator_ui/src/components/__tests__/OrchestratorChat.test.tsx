import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OrchestratorChat } from '../OrchestratorChat';
import { describe, beforeEach, it, expect, vi } from 'vitest';

// Mock scrollTo for jsdom
Element.prototype.scrollTo = vi.fn();

// Mock EventSource for jsdom
class MockEventSource {
    onmessage: ((ev: any) => void) | null = null;
    onerror: ((ev: any) => void) | null = null;
    onopen: ((ev: any) => void) | null = null;
    close = vi.fn();
    addEventListener = vi.fn();
    removeEventListener = vi.fn();
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;
    readyState = 0;
}
vi.stubGlobal('EventSource', MockEventSource);

const addToastMock = vi.fn();

vi.mock('../Toast', () => ({
    useToast: () => ({ addToast: addToastMock }),
}));

/** Route-based fetch mock: responds based on URL pattern (longest match first) */
function createRoutedFetch(overrides: Record<string, () => Promise<any>> = {}) {
    // Sort overrides by key length descending so more specific patterns match first
    const sortedOverrides = Object.entries(overrides).sort((a, b) => b[0].length - a[0].length);

    return vi.fn(async (url: any, _opts?: any) => {
        const urlStr = String(url);

        // Check overrides first (most specific first)
        for (const [pattern, handler] of sortedOverrides) {
            if (urlStr.includes(pattern)) return handler();
        }

        // Default routes
        if (urlStr.includes('/ops/drafts')) {
            return { ok: true, json: async () => [] };
        }
        if (urlStr.includes('/ops/skills')) {
            return { ok: true, json: async () => [] };
        }
        return { ok: true, json: async () => ({}) };
    });
}

describe('OrchestratorChat', () => {
    const chatInputPlaceholder = 'Describe el workflow o usa /comando...';

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('fetch', createRoutedFetch());
    });

    it('muestra intención detectada y estado por pasos al generar draft', async () => {
        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/generate': async () => {
                return {
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
                };
            },
        }));

        render(<OrchestratorChat />);

        const textarea = screen.getByPlaceholderText(chatInputPlaceholder);
        fireEvent.change(textarea, { target: { value: 'help' } });
        fireEvent.click(screen.getByRole('button', { name: /^Enviar$/i }));

        await waitFor(() => {
            expect(screen.getByText('Intent: HELP')).toBeTruthy();
            expect(screen.getByText('Ruta: direct_response')).toBeTruthy();
            expect(screen.getByText(/Intencion detectada: HELP/)).toBeTruthy();
            expect(screen.getByText(/Draft creado: d-help/)).toBeTruthy();
        });
    });

    it('ejecuta flujo chat -> draft -> approve -> run desde UI', async () => {
        let approveCount = 0;
        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/generate': async () => ({
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
            }),
            '/approve': async () => {
                approveCount++;
                return {
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
                };
            },
            '/ops/runs': async () => ({
                ok: true,
                json: async () => ({
                    id: 'r-1',
                    approved_id: 'a-1',
                    status: 'pending',
                    log: [],
                    created_at: '2026-02-19T12:02:00Z',
                }),
            }),
        }));

        render(<OrchestratorChat />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: 'crear plan de pruebas' },
        });
        fireEvent.click(screen.getByRole('button', { name: /^Enviar$/i }));

        const approveButtons = await screen.findAllByRole('button', { name: /aprobar/i });
        fireEvent.click(approveButtons[0]);

        const runButton = await screen.findByRole('button', { name: /ejecutar run/i });
        fireEvent.click(runButton);

        await waitFor(() => {
            expect(screen.getByText(/Run r-1 iniciado para approved a-1/)).toBeTruthy();
        });
    });

    it('slash válido enruta a execute de skills sin pasar por generate', async () => {
        const skillsData = [
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
        ];

        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/skills/skill-1/execute': async () => ({
                ok: true,
                json: async () => ({
                    skill_run_id: 'skill_run_1',
                    skill_id: 'skill-1',
                    replace_graph: false,
                    status: 'queued',
                }),
            }),
            '/ops/skills': async () => ({
                ok: true,
                json: async () => skillsData,
            }),
        }));

        render(<OrchestratorChat />);

        // Wait for skills catalog to load
        await waitFor(() => {
            expect(vi.mocked(fetch)).toHaveBeenCalledWith(
                expect.stringContaining('/ops/skills'),
                expect.anything(),
            );
        });

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: '/explorar' },
        });
        fireEvent.click(screen.getByRole('button', { name: /^Enviar$/i }));

        await waitFor(() => {
            expect(screen.getByText(/Skill \/explorar en cola/)).toBeTruthy();
        });
    });

    it('slash inválido muestra feedback con sugerencia', async () => {
        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/skills': async () => ({
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
            }),
        }));

        render(<OrchestratorChat />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: '/desconocido' },
        });
        fireEvent.click(screen.getByRole('button', { name: /^Enviar$/i }));

        await waitFor(() => {
            expect(screen.getByText(/Comando \/desconocido no encontrado/)).toBeTruthy();
        });
    });

    it('permite enviar mensaje al terminal cuando existe callback', async () => {
        const onSendToTerminal = vi.fn();

        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/generate': async () => ({
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
            }),
        }));

        render(<OrchestratorChat onSendToTerminal={onSendToTerminal} />);

        fireEvent.change(screen.getByPlaceholderText(chatInputPlaceholder), {
            target: { value: 'hola terminal' },
        });
        fireEvent.click(screen.getByRole('button', { name: /^Enviar$/i }));

        const sendButtons = await screen.findAllByRole('button', { name: /enviar a terminal/i });
        fireEvent.click(sendButtons[0]);

        expect(onSendToTerminal).toHaveBeenCalled();
        expect(onSendToTerminal.mock.calls[0][0]).toEqual(
            expect.objectContaining({ source: 'chat' }),
        );
    });

    it('muestra resumen entrante desde terminal', async () => {
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
        vi.stubGlobal('fetch', createRoutedFetch({
            '/ops/drafts': async () => ({
                ok: true,
                json: async () => ([
                    { id: 'd-a', prompt: 'pendiente', status: 'draft', created_at: '2026-02-19T12:00:00Z' },
                    { id: 'd-b', prompt: 'aprobado', status: 'approved', created_at: '2026-02-19T11:59:00Z' },
                    { id: 'd-c', prompt: 'rechazado', status: 'rejected', created_at: '2026-02-19T11:58:00Z' },
                ]),
            }),
        }));

        render(<OrchestratorChat />);

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Pendientes \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Aprobados \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Rech\/Error \(1\)/i })).toBeTruthy();
            expect(screen.getByRole('button', { name: /Todos \(3\)/i })).toBeTruthy();
        });
    });
});
