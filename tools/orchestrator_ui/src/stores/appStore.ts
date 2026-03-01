import { create } from 'zustand';

/* ── Types ─────────────────────────────────────────────── */

/**
 * Current tabs (legacy 8-tab layout, will be reduced to 5 in Phase 1).
 * Keeping full set for backward-compat during migration.
 */
export type SidebarTab =
    | 'graph'
    | 'plans'
    | 'evals'
    | 'metrics'
    | 'security'
    | 'operations'
    | 'settings'
    | 'mastery'
    // Phase 1 additions (will replace metrics+mastery and security+operations)
    | 'analytics';

export interface SessionUser {
    email?: string;
    displayName?: string;
    plan?: string;
    firebaseUser?: boolean;
}

/* ── State shape ───────────────────────────────────────── */

interface AppState {
    /* Auth */
    authenticated: boolean | null;
    bootState: 'checking' | 'ready' | 'offline';
    bootError: string | null;
    sessionUser: SessionUser | null;

    /* Navigation */
    activeTab: SidebarTab;
    selectedNodeId: string | null;

    /* UI panels */
    isCommandPaletteOpen: boolean;
    isChatCollapsed: boolean;
    isProfileOpen: boolean;

    /* Graph bridge */
    graphNodeCount: number;
    activePlanIdFromChat: string | null;
}

/* ── Actions ───────────────────────────────────────────── */

interface AppActions {
    /* Auth */
    setAuthenticated: (v: boolean | null) => void;
    setBootState: (s: AppState['bootState']) => void;
    setBootError: (err: string | null) => void;
    login: (user: SessionUser) => void;
    logout: () => void;

    /* Navigation */
    setActiveTab: (tab: SidebarTab) => void;
    selectNode: (id: string | null) => void;

    /* UI panels */
    toggleCommandPalette: (open?: boolean) => void;
    toggleChat: (collapsed?: boolean) => void;
    toggleProfile: (open?: boolean) => void;

    /* Graph bridge */
    setGraphNodeCount: (n: number) => void;
    setActivePlanIdFromChat: (id: string | null) => void;
}

/* ── Store ──────────────────────────────────────────────── */

export const useAppStore = create<AppState & AppActions>()((set) => ({
    /* ---- defaults ---- */
    authenticated: null,
    bootState: 'checking',
    bootError: null,
    sessionUser: null,

    activeTab: 'graph',
    selectedNodeId: null,

    isCommandPaletteOpen: false,
    isChatCollapsed: false,
    isProfileOpen: false,

    graphNodeCount: -1,
    activePlanIdFromChat: null,

    /* ---- auth actions ---- */
    setAuthenticated: (v) => set({ authenticated: v }),
    setBootState: (s) => set({ bootState: s }),
    setBootError: (err) => set({ bootError: err }),

    login: (user) =>
        set({
            authenticated: true,
            sessionUser: user,
            bootState: 'ready',
            bootError: null,
        }),

    logout: () =>
        set({
            authenticated: false,
            sessionUser: null,
            isProfileOpen: false,
            selectedNodeId: null,
        }),

    /* ---- navigation ---- */
    setActiveTab: (tab) =>
        set((s) => ({
            activeTab: tab,
            selectedNodeId: tab !== 'graph' ? null : s.selectedNodeId,
        })),

    selectNode: (id) =>
        set({
            selectedNodeId: id,
            ...(id ? { activeTab: 'graph' as const } : {}),
        }),

    /* ---- UI panels ---- */
    toggleCommandPalette: (open) =>
        set((s) => ({ isCommandPaletteOpen: open ?? !s.isCommandPaletteOpen })),

    toggleChat: (collapsed) =>
        set((s) => ({ isChatCollapsed: collapsed ?? !s.isChatCollapsed })),

    toggleProfile: (open) =>
        set((s) => ({ isProfileOpen: open ?? !s.isProfileOpen })),

    /* ---- graph bridge ---- */
    setGraphNodeCount: (n) => set({ graphNodeCount: n }),
    setActivePlanIdFromChat: (id) => set({ activePlanIdFromChat: id }),
}));
