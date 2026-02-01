# /refactor — Skill Operativa (Antigravity)

**Objetivo:** Obligar al agente a seguir el documento `docs/REFACTOR_MAIN_LOG.md` y mantener trazabilidad total durante el refactor de `main.py`.

---

## 1) Precondición (obligatoria)
Antes de cualquier acción, el agente **DEBE**:
1. Leer íntegramente `docs/REFACTOR_MAIN_LOG.md`.
2. Confirmar en el chat que ha leído el documento.
3. Seguir los guardrails indicados sin excepción.

---

## 2) Fases y trazabilidad
Para cada fase (F0–F5), el agente **DEBE**:
- Actualizar la sección correspondiente en `docs/REFACTOR_MAIN_LOG.md`.
- Especificar: **qué se hizo, cómo, por qué, resultado y notas operativas**.
- No avanzar de fase con tests en rojo.

---

## 3) Política de no borrado (source of truth)
- **No se elimina ni borra ningún archivo** hasta que el refactor esté completado y validado.

---

## 4) Permisos obligatorios al finalizar
Al terminar el trabajo, el agente **DEBE pedir permiso explícito al usuario** para:
1. **Re-comprobar** todo el trabajo (re-test completo).
2. Ejecutar **`git commit`**.
3. Ejecutar **`git push`**.

---

## 5) Comando
- Este workflow se invoca con el comando: **`/refactor`**
