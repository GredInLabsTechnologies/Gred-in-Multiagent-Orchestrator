import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../App';
import { useAppStore } from '../stores/appStore';

/* ── Mock all child components ── */
vi.mock('../components/Sidebar', () => ({
    Sidebar: () => <div data-testid="sidebar">Sidebar</div>
}));
vi.mock('../components/MenuBar', () => ({
    MenuBar: () => <div data-testid="menu-bar">MenuBar</div>
}));
vi.mock('../components/StatusBar', () => ({
    StatusBar: () => <div data-testid="status-bar">StatusBar</div>
}));
vi.mock('../components/OverlayDrawer', () => ({
    OverlayDrawer: ({ children }: any) => <div data-testid="overlay-drawer">{children}</div>
}));
vi.mock('../components/Shell/CommandPalette', () => ({
    CommandPalette: () => null
}));
vi.mock('../components/ProfilePanel', () => ({
    ProfilePanel: () => null
}));
vi.mock('../components/BackgroundRunner', () => ({
    BackgroundRunner: () => null
}));
vi.mock('../components/SkillsRail', () => ({
    SkillsRail: () => null
}));
vi.mock('../components/LoginModal', () => ({
    LoginModal: ({ onAuthenticated }: { onAuthenticated: () => void }) => (
        <div data-testid="login-modal">
            <button onClick={onAuthenticated}>Login</button>
        </div>
    )
}));

/* Lazy-loaded views */
vi.mock('../views/GraphView', () => ({
    default: () => <div data-testid="graph-view">GraphView</div>
}));
vi.mock('../views/PlansView', () => ({
    default: () => <div data-testid="plans-view">PlansView</div>
}));
vi.mock('../components/SettingsPanel', () => ({
    SettingsPanel: () => <div data-testid="settings-panel">Settings</div>
}));
vi.mock('../components/ProviderSettings', () => ({
    ProviderSettings: () => <div>ProviderSettings</div>
}));
vi.mock('../components/evals/EvalDashboard', () => ({
    EvalDashboard: () => <div>Evals</div>
}));
vi.mock('../components/observability/ObservabilityPanel', () => ({
    ObservabilityPanel: () => <div>Observability</div>
}));
vi.mock('../components/TrustSettings', () => ({
    TrustSettings: () => <div>TrustSettings</div>
}));
vi.mock('../islands/system/MaintenanceIsland', () => ({
    MaintenanceIsland: () => <div>Maintenance</div>
}));
vi.mock('../components/TokenMastery', () => ({
    TokenMastery: () => <div>TokenMastery</div>
}));

/* Hooks */
vi.mock('../hooks/useProfile', () => ({
    useProfile: () => ({ profile: null, loading: false, error: null, unauthorized: false, refetch: vi.fn() })
}));
vi.mock('../hooks/useProviderHealth', () => ({
    useProviderHealth: () => ({})
}));
vi.mock('../hooks/useSkillNotifications', () => ({
    useSkillNotifications: () => {}
}));
vi.mock('../lib/auth', () => ({
    checkSession: vi.fn(),
    logout: vi.fn()
}));
vi.mock('../lib/commands', () => ({
    getCommandHandlers: () => ({})
}));

/* Toast */
vi.mock('../components/Toast', () => ({
    useToast: () => ({ addToast: vi.fn(), removeToast: vi.fn(), toasts: [] })
}));

/* framer-motion minimal mock */
vi.mock('framer-motion', () => ({
    motion: {
        div: ({ children, ...props }: any) => <div {...filterDomProps(props)}>{children}</div>,
    },
    AnimatePresence: ({ children }: any) => <>{children}</>,
}));

function filterDomProps(props: Record<string, any>) {
    const filtered: Record<string, any> = {};
    for (const [k, v] of Object.entries(props)) {
        if (['className', 'style', 'id', 'role', 'aria-label', 'data-testid'].includes(k)) {
            filtered[k] = v;
        }
    }
    return filtered;
}

describe('App', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: () => Promise.resolve({})
        }));
    });

    afterEach(() => {
        // Reset store to defaults
        useAppStore.setState({
            authenticated: null,
            bootState: 'checking',
            activeTab: 'graph',
            activeOverlay: null,
        });
        vi.restoreAllMocks();
    });

    it('shows boot screen when checking', () => {
        useAppStore.setState({ bootState: 'checking', authenticated: null });
        render(<App />);
        expect(screen.getByLabelText('Iniciando GIMO')).toBeInTheDocument();
        expect(screen.getByText('GIMO')).toBeInTheDocument();
        expect(screen.getByText('Iniciando sistema')).toBeInTheDocument();
    });

    it('shows login modal when not authenticated', () => {
        useAppStore.setState({ bootState: 'ready', authenticated: false });
        render(<App />);
        expect(screen.getByTestId('login-modal')).toBeInTheDocument();
    });

    it('shows sidebar and menu when authenticated', async () => {
        useAppStore.setState({ bootState: 'ready', authenticated: true });
        render(<App />);
        await waitFor(() => {
            expect(screen.getByTestId('sidebar')).toBeInTheDocument();
            expect(screen.getByTestId('menu-bar')).toBeInTheDocument();
            expect(screen.getByTestId('status-bar')).toBeInTheDocument();
        });
    });

    it('shows offline alert when backend unavailable', () => {
        useAppStore.setState({ bootState: 'offline', authenticated: true, bootError: 'No hay conexión con el backend.' });
        render(<App />);
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Backend no disponible')).toBeInTheDocument();
    });

    it('has main content area with role=main when authenticated', async () => {
        useAppStore.setState({ bootState: 'ready', authenticated: true });
        render(<App />);
        await waitFor(() => {
            expect(screen.getByRole('main')).toBeInTheDocument();
        });
    });

    it('renders skip navigation link for accessibility', async () => {
        useAppStore.setState({ bootState: 'ready', authenticated: true });
        render(<App />);
        await waitFor(() => {
            expect(screen.getByText('Saltar al contenido principal')).toBeInTheDocument();
        });
    });
});
