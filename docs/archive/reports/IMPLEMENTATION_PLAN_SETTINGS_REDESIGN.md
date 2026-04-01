# IMPLEMENTATION PLAN — Settings Panel Redesign (3 Fases)

> **Contexto**: Auditoría reveló 7 problemas en la sección Settings del Orchestrator UI.  
> **Objetivo**: Convertir Settings de un selector de provider single-agent en un panel de gestión multi-agente con descubrimiento dinámico de modelos.
> **Alcance**: Backend (`gimo_server/services/`) + Frontend (`orchestrator_ui/src/components/`)

---

## Fase 1 — Datos Reales y Descubrimiento Dinámico

**Meta**: Eliminar el hardcoding de modelos y usar APIs reales de descubrimiento.

### 1.1 Implementar `ProviderDiscoveryService` (Backend)

**Archivo**: `tools/gimo_server/services/provider_catalog_service.py`

En lugar de depender solo de `_DEFAULT_PROVIDER_MODELS`, implementar un crawler ligero que use las APIs de discovery de los providers:
- `OpenRouter`: `https://openrouter.ai/api/v1/models` (lista maestra con metadata de calidad y contexto).
- **Extracción de Metadatos**: Capturar campos como `description`, `context_length`, y tags de capacidad (coding, reasoning, tools).
- **Ingesta para el Orquestador**: Guardar esta "ficha técnica" por modelo para que el orquestador pueda decidir dinámicamente: *"Este modelo es 9/10 en coding, mejor lo uso para este Pull Request"*.

> [!TIP]
> Si el usuario no tiene API keys, el sistema puede usar la API pública de OpenRouter para mostrar el catálogo "Disponible" de forma dinámica, marcando cuáles requieren cuenta.

### 1.2 UI: "Capabilities" de un vistazo

**Archivo**: `tools/orchestrator_ui/src/components/ProviderSettings.tsx`

Debajo del nombre de cada modelo en el selector, mostrar micro-etiquetas o un texto breve:
- **Ejemplo**: `GPT-5.3 Codex`
- **Subtexto**: `Excelente en: Código, Razonamiento complejo. | Debilidad: Coste alto.`
- Esto ayuda al usuario a configurar sus "Workers" con conocimiento de causa.

### 1.2 Fix Codex Auth (`failed to fetch`)

**Archivo**: `tools/gimo_server/services/provider_auth_service.py`

El endpoint `POST /ops/provider/codex/device-login` falla si Codex CLI no está instalado.
1. Verificar `codex` en PATH.
2. Devolver JSON con error actionable: `{"status": "error", "message": "Codex CLI no detectado", "action": "npm install -g @openai/codex"}`.
3. Frontend: Mostrar este mensaje con un botón de "Copiar comando de instalación".

### 1.3 Card "Estado efectivo actual" — Refactor Visual

**Archivo**: `tools/orchestrator_ui/src/components/ProviderSettings.tsx`

Convertir la tabla técnica en un "Status Dashboard" compacto con badges de colores para Salud (✅/⚠️/❌) y nombres de modelos amigables.

---

## Fase 2 — Orquestación Multi-Agente

**Meta**: Permitir asignar roles (Orchestrator vs Workers) a diferentes modelos/providers.

### 2.1 Backend: Esquema Multi-Provider

**Archivo**: `tools/gimo_server/services/provider_service.py`

Actualizar `provider.json` para soportar roles específicos:
```json
{
  "roles": {
    "orchestrator": { "provider_id": "codex-main", "model": "gpt-5.3-codex" },
    "workers": [
      { "provider_id": "ollama-local", "model": "qwen2.5-coder:7b" }
    ]
  }
}
```

### 2.2 Recommendation Service: Estrategia de Enjambre

**Archivo**: `tools/gimo_server/services/recommendation_service.py`

Actualizar el algoritmo para recomendar:
1. Un modelo "Cerebro" (Orchestrator): Alta razonamiento, bajo lag.
2. N modelos "Músculo" (Workers): Alta velocidad, locales si hay VRAM.

### 2.3 GICS Feedback Loop: Aprendizaje por Uso (NUEVO)

**Archivo**: `tools/gimo_server/services/gics_service.py` y `ops_service.py`

Implementar un bucle de retroalimentación donde el sistema aprende de sus propios aciertos/errores:
1. **Priors (Fase 1)**: Cargar metadatos de OpenRouter en GICS como "creencia inicial" (`coding: 0.9`).
2. **Evidence (Fase 2)**: Tras cada tarea, registrar en GICS el `outcome`: (éxito/fallo, latencia, coste real).
3. **Refinement**: El `InsightTracker` de GICS ajustará el score real del modelo. Si un modelo "bueno en código" falla 3 veces seguidas en un entorno del usuario, GICS generará una `PredictiveSignal` de anomalía.
4. **Decision**: El Orquestador consultará a GICS antes de asignar una tarea: *"¿Sigue siendo el modelo X fiable para esta tarea según usos anteriores?"*.

---

## Fase 3 — Ubicación UI y Separación de Conceptos

**Meta**: Mover la configuración de providers fuera de Settings para mayor accesibilidad.

### 3.1 Relocalización a MenuBar

**Archivo**: `tools/orchestrator_ui/src/components/MenuBar.tsx`

Mover la gestión de credenciales (Fase 3 del plan anterior) a un nuevo menú **"Conexiones"** en la barra superior.
- Permite configurar LLMs sin salir de la vista de Chat o Graph.
- Muestra indicadores de conexión (luces verdes/rojas) directamente en el menú.

### 3.2 SettingsPanel simplificado

**Archivo**: `tools/orchestrator_ui/src/components/SettingsPanel.tsx`

Settings se queda solo para lógica de **comportamiento**:
- Límites de tokens por sesión.
- Estrategias de limpieza de drafts.
- Configuración de persistencia.

---

## Resumen de Cambios por Archivo

| Archivo | Fase | Cambio Principal |
|---------|------|------------------|
| `provider_catalog_service.py` | 1 | Fetch dinámico via OpenRouter/OpenAI APIs |
| `provider_auth_service.py` | 1 | Validación proactiva de Codex CLI |
| `provider_service.py` | 2 | Schema de roles (Orchestrator + Workers) |
| `MenuBar.tsx` | 3 | Nueva sección "Conexiones" (Credentials Management) |
| `SettingsPanel.tsx` | 3 | Reducción a configuraciones de comportamiento |

