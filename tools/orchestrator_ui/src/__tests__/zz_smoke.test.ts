describe('smoke globals', () => {
    it('works with globals', () => {
        expect(1 + 1).toBe(2)
    })
})

import { describe as d2, it as i2, expect as e2 } from 'vitest'

d2('smoke imports', () => {
    i2('works with imports', () => {
        e2(2 + 2).toBe(4)
    })
})
