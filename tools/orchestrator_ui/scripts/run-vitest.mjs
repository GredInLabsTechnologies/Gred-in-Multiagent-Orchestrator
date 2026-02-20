import { spawnSync } from 'node:child_process'
import { assertSupportedNode } from './check-node-lts.mjs'

assertSupportedNode()

const passthroughArgs = process.argv.slice(2)
const baseArgs = ['run', '--config', './vitest.config.ts', '--root', '.']
const vitestArgs = [...baseArgs, ...passthroughArgs]

const result = spawnSync('vitest', vitestArgs, {
    stdio: 'inherit',
    shell: true,
})

if (typeof result.status === 'number') {
    process.exit(result.status)
}

process.exit(1)
