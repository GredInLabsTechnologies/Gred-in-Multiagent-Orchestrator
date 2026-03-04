# Runbook: Disaster Recovery

## Objetivo
Recuperar operación de GIMO tras fallo crítico preservando integridad de state/worktrees.

## Procedimiento
1. Parar servicio (`sc stop GIMO-Orchestrator`).
2. Respaldar carpetas dañadas y conservar logs forenses.
3. Restaurar `C:/gimo_work/state` desde backup válido.
4. Restaurar `C:/gimo_work/worktrees` si aplica.
5. Validar `policy_hash_runtime` y baseline manifest.
6. Arrancar servicio (`sc start GIMO-Orchestrator`).
7. Ejecutar healthcheck y verificar endpoints críticos.

## Validaciones post-restore
- Estado healthy del servicio.
- No corrupción en runs en curso.
- Override de repo persistente intacto.
- No exposición de secretos en logs.

## Criterio de éxito
Sistema operativo, policy íntegra, y trazabilidad forense preservada.
