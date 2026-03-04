# Runbook: Windows Service Install

## Objetivo
Instalar y operar GIMO como servicio Windows independiente del IDE.

## Precondiciones
- Python/venv de runtime preparado.
- Usuario de servicio sin privilegios admin.
- Carpetas: C:/gimo_work/worktrees, C:/gimo_work/logs, C:/gimo_work/state.

## Instalación
1. Configurar variables de entorno del servicio (sin secretos en claro).
2. Registrar servicio `GIMO-Orchestrator` apuntando al runtime baseline.
3. Definir inicio automático y restart on failure.

## Verificación
- `sc query GIMO-Orchestrator`
- `sc start GIMO-Orchestrator`
- `sc stop GIMO-Orchestrator`
- Reinicio de Windows y validación de arranque healthy.

## ACL mínimo
- Escritura: C:/gimo_work/* y repo target.
- Solo lectura: baseline/runtime.

## Evidencia requerida
- Captura de estado del servicio.
- Evidencia de persistencia de state tras reinicio.
- Evidencia de rotación de logs y ausencia de secretos en logs.
