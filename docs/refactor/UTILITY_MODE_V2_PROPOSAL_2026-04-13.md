# GIMO Mesh — Utility Mode v2 Proposal

> Estado: BORRADOR
> Fecha: 2026-04-13
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

