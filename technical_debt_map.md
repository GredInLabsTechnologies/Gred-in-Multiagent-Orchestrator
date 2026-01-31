# technical_debt_map.md

## 1. Prioritized List of Technical Debt

### 🔴 High Severity (Bloqueadores / Riesgo Crítico)

| Tipo | Deuda Técnica | Evidencia | Impacto | Bloquea Actions Bridge? |
| :--- | :--- | :--- | :--- | :--- |
| **Architecture** | God File: `main.py` (430 líneas) | `tools/repo_orchestrator/main.py` | Mezcla de lógica de negocio, API, Git, y gestión de procesos. Difícil de testear y extender. | **SÍ** (dificulta hooks de automatización) |
| ~~**Security**~~ | ~~God File: `security.py`~~ | ~~`tools/repo_orchestrator/security.py`~~ | ~~Resuelto: TD-007~~ | ✅ |

### 🟡 Medium Severity (Coste de Mantenimiento creciente)

| Tipo | Deuda Técnica | Evidencia | Impacto |
| :--- | :--- | :--- | :--- |
| **Documentation** | Comentarios en Spanglish | `main.py`, `integration_status.md` | Inconsistencia cognitiva para desarrolladores internacionales. |
| **Test** | Falta de Unit Tests Granulares | `tests/` | Las pruebas son mayoritariamente integradas (fuzzing/hardened); falta testing de funciones puras. |
| ~~**Dependency**~~ | ~~Tailwind Zombie~~ | ~~`orchestrator_ui/package.json`~~ | ~~Resuelto: TD-013 (Tailwind está en uso)~~ |
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
- ~~**App.tsx**: Concentra demasiada lógica de estado.~~ → Resuelto: TD-010/TD-011. Nuevo App.tsx minimalista.
- ~~**Ghost Files**: `versions/ProV1.tsx`~~ → Eliminado: TD-010.

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
- **TD-007: Security Module Refactor**: Modularización de `security.py` → `security/` (auth, audit, validation, rate_limit).
- **TD-008: Missing Allowlist Functions**: Implementación de `get_allowed_paths()` y `serialize_allowlist()`.
- **TD-009: Integrity Manifest Update**: Actualización del manifest con archivos del módulo `security/`.
- **TD-010: GIOS Frontend Cleanup**: Eliminación de código GIOS/Assets Engine del frontend.
- **TD-011: Frontend Simplification**: Nuevo diseño Apple-like minimalista.
- **TD-012: TypeScript Strict Mode**: Añadido `noImplicitAny: true` al tsconfig.
- **TD-013: Tailwind Active**: Confirmado que Tailwind SÍ está en uso (no es zombie).
- **TD-014: globalThis Standard**: Uso de `globalThis` en lugar de `window`.
