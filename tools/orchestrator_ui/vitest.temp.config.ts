import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { environment: 'jsdom', include: ['tools/orchestrator_ui/src/__tests__/zz_smoke.test.ts'] } });
