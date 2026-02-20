import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../App';

// Mock Sidebar
vi.mock('../components/Sidebar', () => ({
    Sidebar: () => <div data-testid="sidebar">Sidebar Mock</div>
}));

// Mock GraphCanvas
vi.mock('../components/GraphCanvas', () => ({
    GraphCanvas: () => <div data-testid="graph-canvas">GraphCanvas Mock</div>
}));

// Mock InspectPanel
vi.mock('../components/InspectPanel', () => ({
    InspectPanel: ({ children }: any) => (
        <div data-testid="inspect-panel">{children}</div>
    )
}));

// Mock MaintenanceIsland
vi.mock('../islands/system/MaintenanceIsland', () => ({
    MaintenanceIsland: () => <div data-testid="maintenance-island">MaintenanceIsland Mock</div>
}));

// Mock usePlanEngine
vi.mock('../hooks/usePlanEngine', () => ({
    usePlanEngine: () => ({
        currentPlan: null,
        loading: false,
        createPlan: vi.fn(),
        approvePlan: vi.fn(),
    })
}));

// Mock PlanBuilder
vi.mock('../components/PlanBuilder', () => ({
    PlanBuilder: () => <div data-testid="plan-builder">PlanBuilder Mock</div>
}));

// Mock PlanReview
vi.mock('../components/PlanReview', () => ({
    PlanReview: () => <div data-testid="plan-review">PlanReview Mock</div>
}));

// Mock PlansPanel
vi.mock('../components/PlansPanel', () => ({
    PlansPanel: () => <div data-testid="plans-panel">PlansPanel Mock</div>
}));

// Mock EvalDashboard
vi.mock('../components/evals/EvalDashboard', () => ({
    EvalDashboard: () => <div data-testid="eval-dashboard">EvalDashboard Mock</div>
}));

// Mock ObservabilityPanel
vi.mock('../components/observability/ObservabilityPanel', () => ({
    ObservabilityPanel: () => <div data-testid="observability-panel">ObservabilityPanel Mock</div>
}));

// Mock TrustSettings
vi.mock('../components/TrustSettings', () => ({
    TrustSettings: () => <div data-testid="trust-settings">TrustSettings Mock</div>
}));

// Mock SettingsPanel
vi.mock('../components/SettingsPanel', () => ({
    SettingsPanel: () => <div data-testid="settings-panel">SettingsPanel Mock</div>
}));

// Mock MenuBar
vi.mock('../components/MenuBar', () => ({
    MenuBar: () => <div data-testid="menu-bar">MenuBar Mock</div>
}));

// Mock OrchestratorChat
vi.mock('../components/OrchestratorChat', () => ({
    OrchestratorChat: () => <div data-testid="orchestrator-chat">OrchestratorChat Mock</div>
}));

// Mock WelcomeScreen
vi.mock('../components/WelcomeScreen', () => ({
    WelcomeScreen: () => <div data-testid="welcome-screen">WelcomeScreen Mock</div>
}));

// Mock CommandPalette
vi.mock('../components/Shell/CommandPalette', () => ({
    CommandPalette: () => null
}));

// Mock TokenMastery
vi.mock('../components/TokenMastery', () => ({
    TokenMastery: () => <div data-testid="token-mastery">TokenMastery Mock</div>
}));

// Mock LoginModal
vi.mock('../components/LoginModal', () => ({
    LoginModal: ({ onAuthenticated }: { onAuthenticated: () => void }) => (
        <div data-testid="login-modal">
            <button onClick={onAuthenticated}>Login</button>
        </div>
    )
}));

// Mock Toast
vi.mock('../components/Toast', () => ({
    useToast: () => ({ addToast: vi.fn() })
}));

// Mock ReactFlow
vi.mock('reactflow', () => ({
    ReactFlowProvider: ({ children }: any) => <>{children}</>
}));

// Mock ResizeObserver
globalThis.ResizeObserver = class ResizeObserver {
    observe() { }
    unobserve() { }
    disconnect() { }
};

const mockFetchAuthenticated = () => {
    vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/auth/check')) {
            return { ok: true, json: () => Promise.resolve({ authenticated: true }) } as Response;
        }
        if (urlStr.includes('/ui/status')) {
            return {
                ok: true,
                json: () => Promise.resolve({ version: '1.0.0', service_status: 'RUNNING' })
            } as Response;
        }
        if (urlStr.includes('/ui/graph')) {
            return {
                ok: true,
                json: () => Promise.resolve({ nodes: [{ id: '1' }] })
            } as Response;
        }
        return { ok: true, json: () => Promise.resolve({}) } as Response;
    });
};

describe('App', () => {
    beforeEach(() => {
        vi.mocked(fetch).mockReset();
        mockFetchAuthenticated();
    });

    it('renders footer with company name', async () => {
        render(<App />);
        await waitFor(() => {
            expect(screen.getAllByText('Gred In Labs')[0]).toBeInTheDocument();
        });
    });

    it('renders footer with version', async () => {
        render(<App />);
        await waitFor(() => {
            expect(screen.getByText(/v1\.0\.0/)).toBeInTheDocument();
        });
    });

    it('has correct structure with main and footer', async () => {
        render(<App />);
        await waitFor(() => {
            expect(screen.getByRole('main')).toBeInTheDocument();
            expect(screen.getByRole('contentinfo')).toBeInTheDocument();
        });
    });

    it('applies dark mode classes', async () => {
        const { container } = render(<App />);
        await waitFor(() => {
            const rootDiv = container.firstChild as HTMLElement;
            expect(rootDiv).toHaveClass('min-h-screen');
            expect(rootDiv).toHaveClass('bg-[#000000]');
        });
    });

    it('shows login modal when not authenticated', async () => {
        vi.mocked(fetch).mockImplementation(async (url: any) => {
            const urlStr = String(url);
            if (urlStr.includes('/auth/check')) {
                return { ok: true, json: () => Promise.resolve({ authenticated: false }) } as Response;
            }
            return { ok: true, json: () => Promise.resolve({}) } as Response;
        });
        render(<App />);
        await waitFor(() => {
            expect(screen.getByTestId('login-modal')).toBeInTheDocument();
        });
    });

    it('renders sidebar when authenticated', async () => {
        render(<App />);
        await waitFor(() => {
            expect(screen.getByTestId('sidebar')).toBeInTheDocument();
        });
    });
});
