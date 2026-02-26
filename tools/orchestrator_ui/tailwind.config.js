/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    darkMode: 'class',
    theme: {
        extend: {
            colors: {
                background: "hsl(var(--background))",
                foreground: "hsl(var(--foreground))",
                primary: {
                    DEFAULT: "hsl(var(--primary))",
                    foreground: "hsl(var(--primary-foreground))",
                },
                secondary: {
                    DEFAULT: "hsl(var(--secondary))",
                    foreground: "hsl(var(--secondary-foreground))",
                },
                destructive: {
                    DEFAULT: "hsl(var(--destructive))",
                    foreground: "hsl(var(--destructive-foreground))",
                },
                muted: {
                    DEFAULT: "hsl(var(--muted))",
                    foreground: "hsl(var(--muted-foreground))",
                },
                accent: {
                    DEFAULT: "hsl(var(--accent))",
                    foreground: "hsl(var(--accent-foreground))",
                    primary: 'var(--accent-primary)',
                    approval: 'var(--accent-approval)',
                    trust: 'var(--accent-trust)',
                    alert: 'var(--accent-alert)',
                    warning: 'var(--accent-warning)',
                    purple: 'var(--accent-purple)',
                },
                surface: {
                    0: 'var(--surface-0)',
                    1: 'var(--surface-1)',
                    2: 'var(--surface-2)',
                    3: 'var(--surface-3)',
                },
                'text-primary': 'var(--text-primary)',
                'text-secondary': 'var(--text-secondary)',
                'text-tertiary': 'var(--text-tertiary)',
                'border-primary': 'var(--border-primary)',
                'border-subtle': 'var(--border-subtle)',
                'border-focus': 'var(--border-focus)',
                status: {
                    running: 'var(--status-running)',
                    done: 'var(--status-done)',
                    error: 'var(--status-error)',
                    pending: 'var(--status-pending)',
                    warning: 'var(--status-warning)',
                },
                border: "hsl(var(--border))",
                input: "hsl(var(--input))",
                ring: "hsl(var(--ring))",
            },
            borderRadius: {
                lg: "var(--radius)",
                md: "calc(var(--radius) - 2px)",
                sm: "calc(var(--radius) - 4px)",
            },
            keyframes: {
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                shimmer: {
                    '0%': { backgroundPosition: '-200% 0' },
                    '100%': { backgroundPosition: '200% 0' },
                },
                // Feedback tactile
                press: {
                    '0%': { transform: 'scale(1)' },
                    '50%': { transform: 'scale(0.97)' },
                    '100%': { transform: 'scale(1)' },
                },
                // Entrances
                slideInRight: {
                    '0%': { transform: 'translateX(12px)', opacity: '0' },
                    '100%': { transform: 'translateX(0)', opacity: '1' },
                },
                slideInUp: {
                    '0%': { transform: 'translateY(8px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                },
                slideInDown: {
                    '0%': { transform: 'translateY(-8px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                },
                // Glow states
                glowBreath: {
                    '0%, 100%': { boxShadow: '0 0 12px var(--glow-primary)' },
                    '50%': { boxShadow: '0 0 24px var(--glow-primary)' },
                },
                glowBreathApproval: {
                    '0%, 100%': { boxShadow: '0 0 8px var(--glow-approval)' },
                    '50%': { boxShadow: '0 0 20px var(--glow-approval)' },
                },
                // Status
                statusPulse: {
                    '0%, 100%': { opacity: '1' },
                    '50%': { opacity: '0.6' },
                },
                // Confirmation
                confirmFlash: {
                    '0%': { backgroundColor: 'var(--accent-approval)', opacity: '0.3' },
                    '100%': { backgroundColor: 'transparent', opacity: '0' },
                },
                // Error shake
                shake: {
                    '0%, 100%': { transform: 'translateX(0)' },
                    '20%, 60%': { transform: 'translateX(-4px)' },
                    '40%, 80%': { transform: 'translateX(4px)' },
                },
                // Indeterminate progress
                indeterminate: {
                    '0%': { transform: 'translateX(-100%)' },
                    '100%': { transform: 'translateX(200%)' },
                },
                // Counter/number change
                countUp: {
                    '0%': { transform: 'translateY(100%)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                },
                // Login boot
                scanLine: {
                    '0%': { transform: 'translateX(-100%)', opacity: '0' },
                    '20%': { opacity: '1' },
                    '100%': { transform: 'translateX(100%)', opacity: '0' },
                },
                typeIn: {
                    from: { width: '0' },
                    to: { width: '100%' },
                },
                glowPulse: {
                    '0%, 100%': { boxShadow: '0 0 20px var(--glow-primary)' },
                    '50%': { boxShadow: '0 0 40px var(--glow-primary), 0 0 60px rgba(59, 130, 246, 0.1)' },
                },
                materialize: {
                    '0%': { opacity: '0', transform: 'scale(0.95)' },
                    '100%': { opacity: '1', transform: 'scale(1)' },
                },
                zoomFadeOut: {
                    '0%': { opacity: '1', transform: 'scale(1)' },
                    '100%': { opacity: '0', transform: 'scale(1.05)' },
                },
                orbit: {
                    from: { transform: 'rotate(0deg)' },
                    to: { transform: 'rotate(360deg)' },
                },
            },
            animation: {
                'fade-in': 'fadeIn 0.3s ease-out',
                'pulse-slow': 'pulse 3s ease-in-out infinite',
                'shimmer': 'shimmer 1.5s ease-in-out infinite',
                'press': 'press 150ms ease-out',
                'slide-in-right': 'slideInRight 250ms ease-out',
                'slide-in-up': 'slideInUp 200ms ease-out',
                'slide-in-down': 'slideInDown 200ms ease-out',
                'glow-breath': 'glowBreath 2.5s ease-in-out infinite',
                'glow-breath-approval': 'glowBreathApproval 3s ease-in-out infinite',
                'status-pulse': 'statusPulse 2s ease-in-out infinite',
                'confirm-flash': 'confirmFlash 600ms ease-out forwards',
                'shake': 'shake 400ms ease-out',
                'indeterminate': 'indeterminate 1.5s ease-in-out infinite',
                'count-up': 'countUp 300ms ease-out',
                'scan-line': 'scanLine 0.6s ease-out forwards',
                'type-in': 'typeIn 0.4s steps(20) forwards',
                'glow-pulse': 'glowPulse 2s ease-in-out infinite',
                'materialize': 'materialize 0.5s ease-out forwards',
                'zoom-fade-out': 'zoomFadeOut 0.3s ease-in forwards',
                'orbit': 'orbit 1.2s linear infinite',
            },
        },
    },
    plugins: [],
}
