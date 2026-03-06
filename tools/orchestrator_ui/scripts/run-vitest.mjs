import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assertSupportedNode } from './check-node-lts.mjs'

assertSupportedNode()

const passthroughArgs = process.argv.slice(2)
const baseArgs = ['run', '--config', './vitest.config.ts', '--root', '.']
const vitestArgs = [...baseArgs, ...passthroughArgs]
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const vitestEntrypoint = resolve(projectRoot, 'node_modules', 'vitest', 'vitest.mjs')

const result = spawnSync(process.execPath, [vitestEntrypoint, ...vitestArgs], {
    stdio: 'inherit',
    cwd: projectRoot,
})

if (typeof result.status === 'number') {
    process.exit(result.status)
}

process.exit(1)
