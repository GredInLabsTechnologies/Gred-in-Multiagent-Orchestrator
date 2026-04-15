# GIMO Mesh — Utility Mode v2 Proposal

> Estado: **READY — DEFERRED**
> Última revisión: 2026-04-15 (v2.2)
> Bloqueado por: auditoría de tech debt (caza de brujas — features duplicadas / código legacy)
> Próxima acción: ejecutar §13 (invariante standalone) + §12 (verify + plan expander) tras limpieza del repo
> Objetivo: aumentar el valor real de `utility mode` sin convertirlo en una inferencia barata ni en un segundo orquestador.

---

## Resumen en una frase

`utility mode` debe evolucionar de "unos cuantos comandos ligeros" a un **motor de microtareas deterministas, baratas y paralelizables** para dispositivos modestos.

---

## 1. Qué es hoy `utility mode`

Según la documentación y la implementación actual:

- `utility` = `inference OFF`, `utility ON`, `serve OFF`
- no carga modelo
- no ejecuta GIMO Core
- hace polling de tareas al backend
- ejecuta tareas sandboxed con timeout duro y restricciones de seguridad

Fuentes:

- `docs/GIMO_MESH.md`
- `docs/GIMO_MESH_INVARIANTS.md`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ControlPlaneRuntime.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/MeshAgentService.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/TaskExecutor.kt`

Capacidades actuales observadas:

- `ping`
- `text_validate`
- `text_transform`
- `json_validate`
- `shell_exec` con allowlist
- `file_read`
- `file_hash`

Diagnóstico honesto:

- la idea arquitectónica es correcta
- la ejecución actual es útil pero todavía estrecha
- el riesgo real es que `utility mode` termine siendo demasiado pequeño para justificar su complejidad operativa

---

## 2. Qué problema debemos resolver

Hoy `utility mode` corre el riesgo de quedarse en un punto intermedio incómodo:

- demasiado limitado para aportar mucho valor
- demasiado complejo para ser solo un `ping + regex + hash`

Si queremos que merezca existir, tiene que descargar del host trabajo real pero **sin invadir el territorio de `inference` ni `server mode`**.

La línea buena no es darle "más libertad".

La línea buena es darle **más trabajo determinista**.

---

## 3. Principio rector

`utility mode` no debe intentar pensar.

Debe:

- validar
- transformar
- inspeccionar
- preparar
- indexar
- empaquetar
- postprocesar

No debe:

- decidir semánticamente lo complejo
- elegir estrategia de alto nivel
- sustituir a un modelo
- sustituir al backend

Fórmula de producto:

> `utility mode` = CPU barata para trabajo mecánico bien acotado.

---

## 4. Propuesta: Utility Mode v2

### 4.1 Cambio conceptual

Pasar de:

- "worker de tareas ligeras varias"

a:

- **runtime de microtareas deterministas**

Cada microtarea debe cumplir estas propiedades:

1. timeout corto
2. resultado verificable
3. coste de red razonable frente al trabajo ejecutado
4. no requiere razonamiento abierto
5. puede ejecutarse en hardware modesto

---

## 5. Nuevas capacidades propuestas

### Pack A — Preprocesado útil

Tareas nuevas:

- `text_chunk`
- `text_extract_lines`
- `text_dedup`
- `csv_normalize`
- `jsonl_split`
- `payload_trim`

Valor:

- prepara contexto para modelos o para el backend
- reduce trabajo tonto del host
- aumenta throughput en pipelines grandes

### Pack B — Validación estructural

Tareas nuevas:

- `json_schema_validate`
- `yaml_validate`
- `csv_validate`
- `path_manifest_validate`
- `encoding_check`
- `checksum_manifest_verify`

Valor:

- convierte muchos errores de pipeline en trabajo barato y paralelo
- evita gastar inferencia en comprobaciones mecánicas

### Pack C — Inspección de repos y artefactos

Tareas nuevas:

- `file_stat_batch`
- `file_glob_scan`
- `content_grep`
- `tree_fingerprint`
- `extension_inventory`
- `duplicate_file_detect`

Valor:

- acelera reconocimiento mecánico de repos
- genera inventarios rápidos para el host
- encaja muy bien con móviles sin modelo

### Pack D — Observabilidad y diagnóstico

Tareas nuevas:

- `log_tail_extract`
- `log_pattern_count`
- `metric_snapshot`
- `port_probe`
- `endpoint_health_check`
- `runtime_env_report`

Valor:

- convierte nodos baratos en sondas útiles
- baja carga operacional del host

### Pack E — Postprocesado determinista

Tareas nuevas:

- `result_merge_flat`
- `result_sort_filter`
- `artifact_manifest_build`
- `citation_pack_build`
- `summary_extract_only`

Valor:

- limpieza y empaquetado final sin gastar LLM

---

## 6. Qué NO debe entrar en Utility v2

No meter:

- generación de código
- clasificación semántica compleja
- resolución de ambigüedad
- edición con criterio creativo
- shell arbitrario
- acceso amplio al filesystem
- tareas que se parezcan a un mini-orquestador

Regla:

Si para evaluar bien el resultado haría falta un modelo o juicio humano, probablemente no es tarea de `utility mode`.

---

## 7. Diseño operativo recomendado

### 7.1 Catálogo cerrado por `task_type`

Nada de "comando libre" como capacidad principal.

El centro debe ser un catálogo explícito de tareas bien tipadas:

- input schema claro
- output schema claro
- `min_ram_mb`
- `timeout_seconds`
- restricciones de capacidad

`shell_exec` debe quedarse como capacidad limitada, no como vía general.

### 7.2 Receipts más ricos

Cada microtarea debería producir receipts más útiles:

- `task_type`
- `duration_ms`
- `bytes_in`
- `bytes_out`
- `device_capability_snapshot`
- `result_digest`
- `status`

Esto permitiría medir qué tareas merece la pena mandar a utility y cuáles no.

### 7.3 Agrupación por lotes

Para que compense el roundtrip:

- permitir tareas batch pequeñas
- ejemplo: validar 50 JSON pequeños en una sola asignación
- ejemplo: calcular hashes de N archivos dentro del sandbox en una sola tarea

`utility mode` gana mucho valor cuando amortiza red y scheduling.

---

## 8. Cambios de arquitectura propuestos

### En Android

Extender `TaskExecutor.kt` con módulos separados por dominio:

- `TextTasks`
- `ValidationTasks`
- `FileTasks`
- `ProbeTasks`
- `ResultTasks`

No dejar crecer un único executor monolítico.

### En backend Mesh

Extender el sistema de cola para:

- clasificar tareas como `deterministic_preprocess`, `validation`, `probe`, `artifact_postprocess`
- permitir batching pequeño
- registrar métricas por tipo de tarea

### En GICS / routing

Aprender:

- qué tareas utility salen baratas de verdad
- qué nodos responden mejor a qué tipo
- cuándo utility empeora la latencia total en vez de mejorarla

No hay que hardcodear para siempre la asignación ideal.

---

## 9. Criterio de éxito

`utility mode` merece existir si se demuestra al menos una de estas tres cosas:

1. reduce tiempo total del host en pipelines mixtos
2. reduce coste de inferencia sustituyendo trabajo mecánico
3. permite reutilizar hardware que no sirve para inferencia pero sí para trabajo auxiliar

Si no demuestra eso, debe reducirse o replantearse.

---

## 10. Plan mínimo de implementación

### Fase 1 — Utility útil de verdad

Implementar primero:

- `text_chunk`
- `json_schema_validate`
- `file_glob_scan`
- `content_grep`
- `endpoint_health_check`
- `artifact_manifest_build`

Esto da valor real sin disparar complejidad.

### Fase 2 — Batching y receipts

Añadir:

- batching controlado
- receipts enriquecidos
- métricas por `task_type`

### Fase 3 — Aprendizaje de routing

Añadir:

- recomendación por tipo de microtarea
- preferencia por device profile
- backoff para tareas utility que no compensa distribuir

---

## 11. Conclusión

`utility mode` sí puede volverse importante, pero no intentando hacer de modelo.

Su oportunidad real es otra:

- trabajo mecánico
- barato
- seguro
- verificable
- distribuible

Si GIMO Mesh consigue eso, `utility mode` deja de ser un extra simpático y se convierte en una parte real del throughput del sistema.

---

## 12. Correcciones v2.2 (2026-04-15)

Dos puntos del diseño v2.1 estaban mal planteados. Se rehacen aquí.

### 12.1 `verify_quorum` no debe castigar — debe diagnosticar y enseñar

Diseño v2.1 (RECHAZADO):

> N devices ejecutan la misma tarea → si los hashes divergen, GICS baja el score del divergente.

Problema: una divergencia no es prueba de que el device esté roto. Puede ser:

- bug reproducible en el runtime del device (fixable)
- degradación de hardware (transitoria o permanente)
- quasi-determinismo legítimo (FP en GPU/NPU, kernels distintos)
- corrupción parcial del input (red, almacenamiento)

Castigar sin diagnosticar hunde devices que podían recuperarse y no enseña nada al sistema.

Diseño v2.2:

`verify_quorum` produce una **divergencia**, no un veredicto. La divergencia entra en un loop bidireccional:

1. **Resolución de referencia**
   - tareas hard-deterministas (`file_hash`, `json_schema_validate`, `file_stat_batch`): mayoría manda
   - tareas quasi-deterministas (preprocess de modelo, embeddings): el host recomputa, o se usa un device de referencia explícito
2. **Calibration packet** enviado al device divergente
   - input exacto
   - output canónico
   - su output
   - delta diagnóstico (qué bytes, qué campo, qué ulp si es float)
3. **Self-recalibration en el device**
   - reintenta con fallback path (sin optimización, sin GPU, kernel CPU genérico)
   - reporta qué subsistema causó la divergencia (sandbox, decoder, hasher, runtime LLM)
   - si el reintento converge → el score se recupera y GICS registra la causa raíz
4. **Aprendizaje en GICS**
   - las divergencias se etiquetan por `(task_type, device_class, subsistema, root cause)`
   - los patrones recurrentes generan **calibration rules** (ej. `Mali G77 + json_schema_validate v2 → forzar fallback CPU`)
   - el score solo baja de forma sostenida si el device no puede recuperarse tras N ciclos

Resultado: la divergencia es señal de aprendizaje, no sentencia. Devices con bug reproducible se cuarentenan con un caso de test; devices con drift legítimo se anotan; devices con bug ya corregido recuperan score automáticamente.

Métrica nueva:

- `divergence_recovery_rate` = % de divergencias que terminan resueltas vía recalibración, no vía baneo.

Si esta métrica está por debajo de un umbral, el problema no es del device — es del catálogo de tareas (mal definidas) o del PlanExpander (asignó algo que no era determinista).

---

### 12.2 Descomposición de tareas: el LLM no expande, GIMO expande

Asunción no validada hasta hoy:

> "GICS task patterns descomponen tareas de forma `mágica`."

Nunca se probó y no debe asumirse. Y la alternativa fácil — dejar que el LLM escriba las 400 microtareas — dispara el coste hasta hacer la mesh **más cara** que el host trabajando solo.

Diseño v2.2 — separación estricta de responsabilidades:

| Capa | Quién | Qué produce | Coste |
|---|---|---|---|
| Plan de alto nivel | LLM (caro) | 5–30 nodos con intent + acceptance criteria | $$ |
| Expansión a microtareas | **GIMO PlanExpander** (código + ML pequeño, NO LLM) | N microtareas tipadas | ~0 |
| Routing por device | **GIMO Router** (usa GICS reliability + capability profile) | asignación device → microtarea | ~0 |
| Ejecución | Devices utility | receipts | barato |
| Síntesis | LLM (solo si el nodo lo requiere) | resultado del nodo | $$ |

**PlanExpander**: librería de patrones deterministas en código GIMO. No es un prompt, no es un LLM. Ejemplos:

- `scan_and_validate(glob, schema)` → `file_glob_scan` + N×`json_schema_validate` + `result_merge_flat`
- `fingerprint_repo(root)` → `file_glob_scan` + N×`file_hash` + `tree_fingerprint`
- `diagnose_endpoints(urls)` → N×`endpoint_health_check` + `result_merge_flat`
- `extract_and_chunk(files, chunk_size)` → N×`text_extract_lines` + N×`text_chunk` + `artifact_manifest_build`

El LLM, al escribir el plan, **referencia el pattern por nombre**:

```yaml
- node: validate_repo_schemas
  expand: scan_and_validate
  args:
    glob: "**/*.json"
    schema: ./schemas/manifest.schema.json
  acceptance: all_files_valid
```

GIMO expande con el N real descubierto en runtime ("hay 1247 ficheros JSON en este glob") y emite las microtareas. El LLM nunca ve los 1247 nodos. El coste de inferencia es constante respecto a N.

Para nodos que no encajan en ningún pattern:

- el LLM puede emitir microtareas explícitas pero con **cost gate**: si N > umbral (p.ej. 20), el plan se rechaza y se pide reformular como pattern reutilizable
- o el nodo se marca `utility_eligible=false` → corre en el host

Implicaciones:

- la "task pattern" deja de ser una promesa vaga de GICS y pasa a ser una **librería versionada en código** en `tools/gimo_server/services/mesh/plan_patterns/`
- añadir un pattern nuevo es un PR normal, no entrenamiento de modelo
- el ML solo entra en el Router (qué device es mejor para qué microtarea), no en la expansión
- GICS sigue mandando en routing, pero ya no se le pide adivinar la descomposición

Acciones concretas:

- borrar de toda la doc cualquier afirmación de que "GICS descompone tareas"; sustituir por "GIMO PlanExpander descompone, GICS rutea"
- crear `services/mesh/plan_patterns/` con 4–6 patterns iniciales (los del Pack A/B/C/D)
- añadir `expand: <pattern>` al schema del Plan canónico
- añadir cost-gate en el aprobador de planes: rechazar planes con > N microtareas explícitas que no usen pattern

Esto cierra el riesgo de explosión de coste y elimina la dependencia de una capacidad de GICS que nunca fue probada.

---

## 13. Invariante: GIMO funciona sin mesh

Las secciones anteriores estaban escritas como si la mesh fuese obligatoria. No lo es. **GIMO debe funcionar perfectamente con cero devices conectados.** La mesh mejora throughput y permite reusar hardware barato, pero no es requisito.

Esto obliga a reposicionar dónde vive cada cosa.

### 13.1 Cuatro capas, una sola autoridad

| Capa | Vive en | Existe sin mesh | Qué hace |
|---|---|---|---|
| **PlanExpander** | `gimo_server/services/plan/expander.py` | Sí | Expande nodos del plan a microtareas tipadas usando la librería de patterns |
| **MicrotaskExecutor** | `gimo_server/services/microtasks/` | Sí | Ejecuta microtareas en pool local del host (process pool / asyncio) |
| **VerifyEngine** | `gimo_server/services/verify/` | Sí | Valida resultados contra fuentes de verdad (fixtures, recompute, quorum) |
| **MeshTransport** | `gimo_server/services/mesh/` | **Opcional** | Plano de distribución: enruta microtareas a devices remotos |

La separación crítica:

- **PlanExpander, MicrotaskExecutor y VerifyEngine son GIMO core**, no mesh.
- **MeshTransport es un plano de transporte** que se enchufa por encima cuando hay devices disponibles.
- El Router es siempre el mismo: pregunta "¿hay devices con capability X y trust Y?". Si la respuesta es "no, solo el host", todo corre local y el plan se completa igual.

### 13.2 Modos de operación

| Modo | Devices mesh | Ejecución de microtareas | Verificación |
|---|---|---|---|
| **Standalone** | 0 | Pool local del host | fixtures + recompute |
| **Mesh** | ≥1 | Distribuida (Router decide) | fixtures + recompute + quorum opcional |
| **Hybrid** | ≥1 pero limitado | Mixta: parte local, parte remota | igual que mesh |

Standalone no es un modo degradado — es el modo por defecto. La mesh es una optimización.

### 13.3 Reformulación de §12.1 sin mesh

`verify_quorum` era un mal nombre porque implicaba mesh. Lo correcto es **VerifyEngine con fuentes de verdad pluggables**:

- `fixture` — output esperado declarado en el catálogo de la microtarea (para tareas hard-deterministas con caso conocido)
- `recompute` — el host vuelve a ejecutar la microtarea con un fallback path y compara
- `quorum` — N devices mesh ejecutan y se compara (solo disponible en modo mesh con N≥2)

El loop de aprendizaje (calibration packet → self-recalibration → GICS registra root cause) es **el mismo en los tres casos**. La diferencia es de dónde sale el "output canónico":

- en standalone, sale del fixture o del recompute local
- en mesh, también puede salir del quorum

GICS aprende igual. El device aprende igual. La métrica `divergence_recovery_rate` se mantiene y aplica también al propio host (si el host diverge entre dos kernels, también es señal).

### 13.4 Reformulación de §12.2 sin mesh

El PlanExpander vive en core y **no sabe nada de devices**. Su API:

```
expand(plan_node) -> list[Microtask]
```

Devuelve microtareas tipadas. Quién las ejecuta es decisión del Router:

- standalone: todas al pool local
- mesh: el Router decide cuáles enviar fuera basándose en GICS reliability + capacity + coste de red
- el cost-gate (rechazar planes con > N microtareas explícitas no-pattern) aplica igual sin mesh — protege al host de auto-saturarse

Esto significa que **los patterns** (`scan_and_validate`, `fingerprint_repo`, etc.) son útiles en standalone también: paralelizan trabajo en el pool local del host y evitan que el LLM tenga que escribir 1247 nodos para validar 1247 ficheros.

### 13.5 Implicaciones de packaging y rutas

- mover los patterns propuestos en §12.2 de `services/mesh/plan_patterns/` a **`services/plan/patterns/`** (sin "mesh" en la ruta)
- `MicrotaskExecutor` es nuevo y vive en `services/microtasks/` — incluye el pool local y la API que mesh consume cuando enruta fuera
- `MeshTransport` queda como un consumidor más del MicrotaskExecutor, no como su dueño
- el catálogo de microtareas (`task_type` + schemas + `min_ram_mb` + `timeout_seconds`) vive en core, no en mesh
- los Packs A/B/C/D/E/F del §5 son librería core, ejecutables en el host sin ningún device conectado

### 13.6 Test de aceptación de la invariante

Un test simple debe pasar:

> Arrancar GIMO con `mesh_enabled=false`. Lanzar un plan que use `expand: scan_and_validate`. Debe completarse correctamente, con todas las microtareas ejecutadas en el pool local del host y verificadas contra fixture/recompute. Sin un solo device mesh involucrado.

Si ese test no pasa, el diseño está mesh-centrista y hay que arreglarlo antes de seguir.

