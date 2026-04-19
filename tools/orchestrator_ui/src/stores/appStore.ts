import { create } from 'zustand';
import { API_BASE, SkillRun } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

/* ── Types ─────────────────────────────────────────────── */

/**
 * Primary sidebar tabs — only the essentials.
 * Everything else opens as an overlay drawer.
 */
export type SidebarTab = 'graph' | 'plans' | 'threads';

/**
 * Overlay drawers that slide over the main view.
 * These never replace the graph — they float on top.
 */
export type OverlayId =
    | 'connections'
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
    isSkillsDropdownOpen: boolean;
    skillsDockEdge: 'top' | 'left' | 'right' | 'bottom';

    /* Graph bridge */
    graphNodeCount: number;
    activePlanIdFromChat: string | null;

    /* Background Skills */
    skillRuns: Record<string, SkillRun>;
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
    toggleSkillsDropdown: (open?: boolean) => void;
    setSkillsDockEdge: (edge: AppState['skillsDockEdge']) => void;

    /* Graph bridge */
    setGraphNodeCount: (n: number) => void;
    setActivePlanIdFromChat: (id: string | null) => void;

    /* Background Skills */
    updateSkillRun: (run: Partial<SkillRun> & { id: string }) => void;
    removeSkillRun: (id: string) => void;
}

/* ── Helpers ───────────────────────────────────────────── */

const SIDEBAR_TABS = new Set<string>(['graph', 'plans', 'threads']);
const OVERLAY_IDS = new Set<string>(['connections', 'settings', 'evals', 'metrics', 'mastery', 'security', 'operations']);

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
    isSkillsDropdownOpen: false,
    skillsDockEdge: (function (): AppState['skillsDockEdge'] {
        try {
            const saved = localStorage.getItem('gimo_skills_dock_edge');
            if (saved && ['top', 'left', 'right', 'bottom'].includes(saved)) return saved as AppState['skillsDockEdge'];
        } catch {
            // localStorage may be unavailable in non-browser/test contexts
        }
        return 'top';
    })(),

    graphNodeCount: -1,
    activePlanIdFromChat: null,

    skillRuns: {},

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
            bootState: 'offline',
            bootError: null,
            isProfileOpen: false,
            selectedNodeId: null,
            activeOverlay: null,
        }),

    checkSession: async () => {
        const store = useAppStore.getState();
        if (store.authenticated === false) return;
        try {
            const resp = await fetchWithRetry(`${API_BASE}/me`, { credentials: 'include' });
            if (resp.ok) {
                const user = await resp.json();
                store.login(user);
            } else {
                store.logout();
            }
        } catch {
            store.logout();
        }
    },

    revalidateSession: async () => {
        const store = useAppStore.getState();
        if (store.authenticated === false) return;
        try {
            const resp = await fetchWithRetry(`${API_BASE}/me`, { credentials: 'include' });
            if (resp.ok) {
                const user = await resp.json();
                store.login(user);
            }
        } catch {
            // ignore
        }
    },

    /* ---- navigation ---- */
    setActiveTab: (tab) =>
        set((s) => ({
            activeTab: tab,
            selectedNodeId: tab === 'graph' ? s.selectedNodeId : null,
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
                    selectedNodeId: target === 'graph' ? s.selectedNodeId : null,
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

    toggleSkillsDropdown: (open) =>
        set((s) => ({ isSkillsDropdownOpen: open ?? !s.isSkillsDropdownOpen })),

    setSkillsDockEdge: (edge) => {
        localStorage.setItem('gimo_skills_dock_edge', edge);
        set({ skillsDockEdge: edge });
    },

    /* ---- graph bridge ---- */
    setGraphNodeCount: (n) => set({ graphNodeCount: n }),
    setActivePlanIdFromChat: (id) => set({ activePlanIdFromChat: id }),

    /* ---- background skills ---- */
    updateSkillRun: (run) =>
        set((s) => ({
            skillRuns: {
                ...s.skillRuns,
                [run.id]: {
                    ...(s.skillRuns[run.id] || {
                        status: 'queued',
                        progress: 0,
                        message: '',
                        started_at: new Date().toISOString(),
                    }),
                    ...run,
                },
            },
        })),

    removeSkillRun: (id) =>
        set((s) => {
            const { [id]: _, ...rest } = s.skillRuns;
            return { skillRuns: rest };
        }),
}));
