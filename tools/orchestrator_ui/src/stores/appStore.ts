import { create } from 'zustand';

/* ── Types ─────────────────────────────────────────────── */

/**
 * Primary sidebar tabs — only the essentials.
 * Everything else opens as an overlay drawer.
 */
export type SidebarTab = 'graph' | 'plans';

/**
 * Overlay drawers that slide over the main view.
 * These never replace the graph — they float on top.
 */
export type OverlayId =
    | 'settings'
    | 'evals'
    | 'metrics'
    | 'mastery'
    | 'security'
    | 'operations'
    | null;

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
    activeOverlay: OverlayId;

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
    openOverlay: (id: NonNullable<OverlayId>) => void;
    closeOverlay: () => void;

    /**
     * Legacy compat: accepts old 8-tab IDs and routes them
     * to either a sidebar tab or an overlay.
     */
    navigate: (target: string) => void;

    /* UI panels */
    toggleCommandPalette: (open?: boolean) => void;
    toggleChat: (collapsed?: boolean) => void;
    toggleProfile: (open?: boolean) => void;

    /* Graph bridge */
    setGraphNodeCount: (n: number) => void;
    setActivePlanIdFromChat: (id: string | null) => void;
}

/* ── Helpers ───────────────────────────────────────────── */

const SIDEBAR_TABS = new Set<string>(['graph', 'plans']);
const OVERLAY_IDS = new Set<string>(['settings', 'evals', 'metrics', 'mastery', 'security', 'operations']);

/* ── Store ──────────────────────────────────────────────── */

export const useAppStore = create<AppState & AppActions>()((set) => ({
    /* ---- defaults ---- */
    authenticated: null,
    bootState: 'checking',
    bootError: null,
    sessionUser: null,

    activeTab: 'graph',
    selectedNodeId: null,
    activeOverlay: null,

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
            activeOverlay: null,
        }),

    /* ---- navigation ---- */
    setActiveTab: (tab) =>
        set((s) => ({
            activeTab: tab,
            selectedNodeId: tab !== 'graph' ? null : s.selectedNodeId,
            activeOverlay: null, // close overlay when switching tabs
        })),

    selectNode: (id) =>
        set({
            selectedNodeId: id,
            ...(id ? { activeTab: 'graph' as const } : {}),
        }),

    openOverlay: (id) => set({ activeOverlay: id }),
    closeOverlay: () => set({ activeOverlay: null }),

    navigate: (target) =>
        set((s) => {
            if (SIDEBAR_TABS.has(target)) {
                return {
                    activeTab: target as SidebarTab,
                    activeOverlay: null,
                    selectedNodeId: target !== 'graph' ? null : s.selectedNodeId,
                };
            }
            if (OVERLAY_IDS.has(target)) {
                return { activeOverlay: target as NonNullable<OverlayId> };
            }
            // Unknown target — ignore
            return {};
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
