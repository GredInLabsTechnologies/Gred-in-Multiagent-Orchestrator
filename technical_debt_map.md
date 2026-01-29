# technical_debt_map.md

## 1. Prioritized List of Technical Debt

### 🔴 High Severity (Bloqueadores / Riesgo Crítico)

| Tipo | Deuda Técnica | Evidencia | Impacto | Bloquea Actions Bridge? |
| :--- | :--- | :--- | :--- | :--- |
| **Architecture** | God File: `main.py` (430 líneas) | `tools/repo_orchestrator/main.py` | Mezcla de lógica de negocio, API, Git, y gestión de procesos. Difícil de testear y extender. | **SÍ** (dificulta hooks de automatización) |
| **Security** | God File: `security.py` (356 líneas) | `tools/repo_orchestrator/security.py` | Mezcla de Auth, Registro de Repos, Validación de Paths y Logs. Riesgo de bugs en validación. | **SÍ** (acoplamiento fuerte con sesión HTTP) |

### 🟡 Medium Severity (Coste de Mantenimiento creciente)

| Tipo | Deuda Técnica | Evidencia | Impacto |
| :--- | :--- | :--- | :--- |
| **Documentation** | Comentarios en Spanglish | `main.py`, `integration_status.md` | Inconsistencia cognitiva para desarrolladores internacionales. |
| **Test** | Falta de Unit Tests Granulares | `tests/` | Las pruebas son mayoritariamente integradas (fuzzing/hardened); falta testing de funciones puras. |
| **Dependency** | Tailwind Zombie | `orchestrator_ui/package.json` | Dependencia instalada pero el CSS es Vanilla. Aumenta peso del build innecesariamente. |
| **Architecture** | Inicialización en Módulo | `main.py`:115, `security.py`:338 | Side-effects al importar (start_time, mkdir). Dificulta testing paralelo. |

### 🟢 Baja Severity (Inconsistencia / Fricción Menor)

| Tipo | Deuda Técnica | Evidencia | Impacto |
| :--- | :--- | :--- | :--- |
| **Code** | Inconsistencia en Respuestas | `main.py`:262 (`__dict__`) vs Pydantic | Inconsistencia en la serialización de datos de la API. |
| **Architecture** | TTLs Hardcodeados | `config.py`:44, 49 | Dificulta la configuración dinámica para diferentes workloads. |

---

## 2. Mapa Detallado por Componente

### Backend (`tools/repo_orchestrator`)
- **Main Controller**: Debe dividirse en `routes.py`, `services/git_service.py`, `services/snapshot_manager.py`.
- **Security Logic**: La lógica de "Registry" (`repo_registry.json`) debe separarse de la lógica de "Path Validation".

### Frontend (`tools/orchestrator_ui`)
- **App.tsx**: Concentra demasiada lógica de estado. Debe moverse a `hooks/useOrchestrator.ts`.
- **Ghost Files**: Evaluar si `versions/ProV1.tsx` es necesario o es residuo de una migración.

---

## 3. Quick Wins vs Refactors Estructurales

### Quick Wins (Bajo coste, alto valor)
1. **Internal Path Hardcoding**: Refactorizar paths absolutos a variables de entorno dinámicas.

### Refactors Estructurales (Necesarios para el Actions Bridge)
1. **Service Layer Pattern**: Sacar la lógica de Git y File System de `main.py` a clases/funciones independientes que puedan llamarse desde una CLI.
2. **Configuración Dinámica**: Mover TTLs y paths sensibles a variables de entorno reales, no solo fallbacks en `config.py`.

---

## 4. Deuda Técnica Resuelta (Modernización 2026)
- **TD-001: Missing Requirements**: Se generó `requirements.txt` locked.
- **TD-002: Service Management**: Extracción a `SystemService`.
- **TD-003: Headless Bypass**: Bypass de Tkinter detectado por variables de entorno.
- **TD-004: Decoupled open_repo**: Eliminación de dependencia de `explorer.exe` en el backend.
- **TD-005: Removal of Legacy Dashboard**: Eliminación física de `tools/orchestrator_dashboard`.
- **TD-006: Duplicate Search API**: Limpieza de decoradores redundantes en `main.py`.
