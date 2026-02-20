import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

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

// Mock URL.createObjectURL and revokeObjectURL for export tests
globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
globalThis.URL.revokeObjectURL = vi.fn()
