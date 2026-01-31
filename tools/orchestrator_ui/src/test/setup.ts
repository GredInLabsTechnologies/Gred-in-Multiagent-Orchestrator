import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Cleanup after each test
afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.restoreAllMocks()
})

// Mock globalThis.location for API_BASE
Object.defineProperty(globalThis, 'location', {
    value: {
        hostname: 'localhost'
    },
    writable: true
})

// Mock fetch globally
globalThis.fetch = vi.fn()

// Mock URL.createObjectURL and revokeObjectURL for export tests
globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
globalThis.URL.revokeObjectURL = vi.fn()
