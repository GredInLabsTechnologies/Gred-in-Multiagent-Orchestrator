const major = Number.parseInt(process.versions.node.split('.')[0], 10)

const isSupported = Number.isFinite(major) && (major === 20 || major === 22 || major === 24)

if (!isSupported) {
    console.error('\n[orchestrator_ui] Runtime no soportado para tests frontend.')
    console.error(`[orchestrator_ui] Node actual: v${process.versions.node}`)
    console.error('[orchestrator_ui] Usa Node 20, 22 o 24 para ejecutar Vitest en este proyecto.')
    console.error('[orchestrator_ui] Ejemplo: nvm use 22 && npm --prefix tools/orchestrator_ui run test -- src/components/__tests__/MenuBar.test.tsx\n')
    process.exit(1)
}
