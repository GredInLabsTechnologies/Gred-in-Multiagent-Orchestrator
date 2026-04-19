import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'
// Initialize i18n so components using useTranslation() render actual strings
// instead of raw keys. Tests that assert on user-visible text rely on this.
import '../i18n'

// Mock globalThis.location for API_BASE (safe across runtimes/jsdom versions)
try {
    Object.defineProperty(globalThis, 'location', {
        value: {
            hostname: 'localhost'
        },
        writable: true,
        configurable: true
    })
} catch {
    // Fallback for environments where `location` cannot be redefined.
}

// Mock fetch globally (safe across Node versions)
try {
    vi.stubGlobal('fetch', vi.fn())
} catch {
    // Ignore when runtime does not allow overriding global fetch.
}

// Stub fetchWithRetry as a pass-through to global `fetch`. Hooks that fetch
// via fetchWithRetry would otherwise retry 3× with 500-4000ms backoff on
// rejected promises and 5xx, which breaks single-shot `mockRejectedValueOnce`
// / `mockResolvedValueOnce` patterns used across hook tests. No existing test
// exercises retry/backoff logic directly, so this is safe.
vi.mock('../lib/fetchWithRetry', () => ({
    fetchWithRetry: (input: RequestInfo | URL, init?: RequestInit) => fetch(input, init),
}))

// Mock URL.createObjectURL and revokeObjectURL for export tests
globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
globalThis.URL.revokeObjectURL = vi.fn()

// Mock canvas getContext for tests rendering AuthGraphBackground or other canvas components
HTMLCanvasElement.prototype.getContext = () => {
    return {
        fillRect: vi.fn(),
        clearRect: vi.fn(),
        getImageData: vi.fn((_x: number, _y: number, w: number, h: number) => {
            return {
                data: new Array(w * h * 4)
            };
        }),
        putImageData: vi.fn(),
        createImageData: vi.fn(),
        setTransform: vi.fn(),
        drawImage: vi.fn(),
        save: vi.fn(),
        fillText: vi.fn(),
        restore: vi.fn(),
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        closePath: vi.fn(),
        stroke: vi.fn(),
        translate: vi.fn(),
        scale: vi.fn(),
        rotate: vi.fn(),
        arc: vi.fn(),
        fill: vi.fn(),
        measureText: vi.fn(() => {
            return { width: 0 };
        }),
        transform: vi.fn(),
        rect: vi.fn(),
        clip: vi.fn(),
    } as any;
};
