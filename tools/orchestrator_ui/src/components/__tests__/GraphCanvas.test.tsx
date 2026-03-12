import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('reactflow', () => ({
    default: ({ children }: any) => <div data-testid="react-flow">{children}</div>,
    Background: () => <div data-testid="rf-background" />,
    Controls: () => <div data-testid="rf-controls" />,
    MiniMap: () => <div data-testid="rf-minimap" />,
    Panel: ({ children }: any) => <div data-testid="rf-panel">{children}</div>,
    useNodesState: () => [[], vi.fn(), vi.fn()],
    useEdgesState: () => [[], vi.fn(), vi.fn()],
    useReactFlow: () => ({ project: vi.fn((pos: any) => pos), fitView: vi.fn(), getNodes: () => [], getEdges: () => [] }),
    addEdge: vi.fn(),
    MarkerType: { ArrowClosed: 'arrowclosed' },
}));

vi.mock('reactflow/dist/style.css', () => ({}));

vi.mock('../Toast', () => ({
    useToast: () => ({ addToast: vi.fn(), removeToast: vi.fn(), toasts: [] })
}));

vi.mock('../../hooks/useAvailableModels', () => ({
    useAvailableModels: () => ({ models: [] })
}));

vi.mock('../../hooks/useMasteryService', () => ({
    useMasteryService: () => ({ balance: 0, spend: vi.fn() })
}));

const defaultGraphState: Record<string, any> = {
    economyLayerEnabled: false,
    sessionEconomy: { spendUsd: 0, savingsUsd: 0, nodesOptimized: 0 },
    ecoMode: false,
    selectedEditNodeId: null,
    setSelectedEditNodeId: vi.fn(),
    setEconomyLayerEnabled: vi.fn(),
    setEcoMode: vi.fn(),
    setSessionEconomy: vi.fn(),
};
vi.mock('../Graph/useGraphStore', () => ({
    useGraphStore: Object.assign(
        vi.fn((selector: any) => selector ? selector(defaultGraphState) : defaultGraphState),
        { getState: () => defaultGraphState, subscribe: vi.fn() }
    ),
    normalizeServerNodes: vi.fn(() => []),
    normalizeServerEdges: vi.fn(() => []),
    toEditableNode: vi.fn(),
    extractDraftInfo: vi.fn(() => null),
    computeProgress: vi.fn(() => ({ total: 0, done: 0, pct: 0 })),
    validateGraph: vi.fn(() => ({ valid: true, errors: [] })),
    buildPlanPayload: vi.fn(() => ({})),
    ROLE_TEMPLATES: [],
}));

vi.mock('framer-motion', () => ({
    AnimatePresence: ({ children }: any) => <>{children}</>,
    motion: { div: (props: any) => <div {...props} /> },
}));

vi.mock('../ComposerNode', () => ({
    ComposerNode: () => <div>Node</div>
}));
vi.mock('../PlanOverlayCard', () => ({
    PlanOverlayCard: () => null
}));
vi.mock('../Graph/GraphToolbar', () => ({
    GraphToolbar: () => null
}));
vi.mock('../Graph/SkillCreateModal', () => ({
    SkillCreateModal: () => null
}));
vi.mock('../Graph/NodeEditor', () => ({
    NodeEditor: () => null
}));
vi.mock('../Graph/ProgressBar', () => ({
    ProgressBar: () => null
}));
vi.mock('../Graph/AnimatedEdge', () => ({
    AnimatedEdge: () => null
}));

import { GraphCanvas } from '../GraphCanvas';

describe('GraphCanvas', () => {
    it('renders ReactFlow container', () => {
        render(<GraphCanvas onNodeSelect={vi.fn()} selectedNodeId={null} />);
        expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    });

    it('renders MiniMap', () => {
        render(<GraphCanvas onNodeSelect={vi.fn()} selectedNodeId={null} />);
        expect(screen.getByTestId('rf-minimap')).toBeInTheDocument();
    });

    it('renders panel label', () => {
        render(<GraphCanvas onNodeSelect={vi.fn()} selectedNodeId={null} />);
        expect(screen.getByText('Grafo de Orquestación')).toBeInTheDocument();
    });
});
