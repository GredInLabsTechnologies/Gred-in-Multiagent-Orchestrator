/**
 * Glass morphism utility classes for consistent premium UI surfaces.
 *
 * Usage:  <div className={glass.panel}> ... </div>
 *
 * Each variant targets a specific elevation level:
 *   panel   → primary content areas (sidebar, main views)
 *   card    → nested cards within panels
 *   toolbar → floating action bars, toolbars
 *   overlay → modal/dropdown backdrops
 *   subtle  → barely-there glass for hover states
 */
export const glass = {
    /** Primary panels — sidebars, main content areas */
    panel: [
        'bg-surface-1/80',
        'backdrop-blur-xl',
        'border border-white/[0.06]',
        'shadow-lg shadow-black/20',
    ].join(' '),

    /** Nested cards inside panels */
    card: [
        'bg-surface-2/70',
        'backdrop-blur-lg',
        'border border-white/[0.04]',
        'shadow-md shadow-black/15',
    ].join(' '),

    /** Floating toolbars, action bars */
    toolbar: [
        'bg-surface-0/60',
        'backdrop-blur-2xl',
        'border border-white/[0.08]',
        'shadow-xl shadow-black/30',
    ].join(' '),

    /** Modal/dropdown overlays */
    overlay: 'bg-black/40 backdrop-blur-sm',

    /** Barely-there glass for hover states */
    subtle: [
        'bg-surface-3/40',
        'backdrop-blur-md',
        'border border-white/[0.03]',
    ].join(' '),
} as const;

/**
 * Glow shadow utilities keyed by semantic color.
 * Usage:  <div className={glow.primary}> ... </div>
 */
export const glow = {
    primary: 'shadow-[0_0_20px_var(--glow-primary)]',
    approval: 'shadow-[0_0_16px_var(--glow-approval)]',
    trust: 'shadow-[0_0_16px_var(--glow-trust)]',
    alert: 'shadow-[0_0_16px_var(--glow-alert)]',
} as const;
