# GIL Orchestrator (Repo Management Tool) - [PRODUCTION READY]

Este repositorio contiene la herramienta de gestión y orquestación de repositorios (GIL Orchestrator), diseñada para exponer repositorios locales de forma segura a través de túneles Cloudflare y permitir la auditoría en tiempo real.

## Estado del Proyecto
- **Modo**: ESTRICTO SOLO LECTURA (Snapshot Read-Only).
- **Seguridad**: Certificada mediante Quality Gates (Integridad, Fuzzing, ASVS L3 Logic).
- **Limpieza**: Depurado de cualquier configuración externa (Rainmeter/Taskbar).

## Componentes
- **API Service**: `tools/repo_orchestrator/` (FastAPI).
- **Dashboard**: `tools/orchestrator_dashboard/` (React + Vite).
- **Service Deployment**: `scripts/` (Windows Service & Monitoring).

## Guía de Despliegue de Producción
1. **Configurar .env**: Asegúrate de que `ORCH_TOKEN` y `ORCH_REPO_ROOT` sean correctos.
2. **Instalar Dependencias**: `pip install -r requirements.txt` (si aplica) o usar el entorno virtual configurado.
3. **Activar Túnel**: `cloudflared service install <TOKEN>` para persistencia.
4. **Lanzar**: Ejecutar `scripts/start_orch.cmd`.

## Auditoría y Control
Cada lectura de archivo se registra con un Hash SHA-256 en `logs/orchestrator_audit.log` y se sirve desde una copia temporal para proteger el código original.
