import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OrchestratorChat } from '../OrchestratorChat';

const addToastMock = vi.fn();

vi.mock('../Toast', () => ({
    useToast: () => ({ addToast: addToastMock }),
}));

describe('OrchestratorChat', () => {
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

        fireEvent.change(screen.getByPlaceholderText('Describe el workflow para generar un draft...'), {
            target: { value: 'help' },
        });
        fireEvent.click(screen.getByRole('button', { name: /enviar/i }));

        await waitFor(() => {
            expect(screen.getByText('Intent: HELP')).toBeTruthy();
            expect(screen.getByText('Ruta: direct_response')).toBeTruthy();
            expect(screen.getByText(/Intención detectada: HELP/)).toBeTruthy();
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

        fireEvent.change(screen.getByPlaceholderText('Describe el workflow para generar un draft...'), {
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
                expect.stringContaining('/ops/runs'),
                expect.objectContaining({ method: 'POST' })
            );
        });
    });
});
