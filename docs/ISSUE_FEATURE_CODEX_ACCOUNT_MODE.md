# Feature: Soporte Nativo para "Account Mode" (Suscripción) en Codex sin API Key

## 1. Contexto y Problema
Actualmente, los usuarios de **Cline** pueden utilizar los modelos de Codex autenticándose a través de su cuenta/suscripción (ChatGPT Plus/Pro), lo cual se realiza mediante un flujo OAuth en el navegador o mediante `codex login`, sin necesidad de proveer una API Key directamente.

En **GIMO**, la interfaz de `ProviderSettings.tsx` permite habilitar un modo `account` (si la feature flag `ORCH_CODEX_ACCOUNT_MODE_ENABLED=true` está activa). Sin embargo, la experiencia de usuario se limita a solicitar un texto (`account/session token`). 
El adaptador de backend (`codex.py`) invoca el CLI `codex execute ...` asumiendo que el token se proveerá en el contexto o que el CLI ya está pre-autenticado en el sistema anfitrión.

**Objetivo:** Modificar GIMO para brindar una experiencia de usuario (UX) de primer nivel, similar a Cline, que permita al usuario autenticar su cuenta de OpenAI/Codex sin gestionar claves crudas, resolviendo cómo el backend de GIMO se comunica de forma segura con el CLI de Codex.

---

## 2. Hallazgos de la Investigación Previa
- **Cline:** Utiliza una integración OAuth profunda (botón "Sign in with OpenAI") que obtiene y refresca access tokens de forma transparente.
- **Codex CLI:** Soporta nativamente la autenticación interactiva ejecutando `codex login` (abre el navegador) o `codex login --device-auth` (headless).
- **GIMO Backend (`provider_auth_service.py`):** Si se envía un `account`, lo guarda como variable de entorno `ORCH_PROVIDER_CODEX_ACCOUNT_TOKEN` y guarda la referencia `auth_ref`. 
- **GIMO Adapter (`codex.py`):** Llama a `codex execute <task>`. No gestiona flujos interactivos de login. Si el entorno del host (donde corre gimo_server) ya tiene la sesión cacheada de `codex login`, funciona. Si no, falla al no tener credenciales.

**Hipótesis de Brecha:** GIMO necesita o bien (A) guiar al usuario para pre-autenticar el CLI en su máquina anfitriona, o (B) implementar el flujo `--device-auth` o inyección de access token directamente a través de la UI hacia el backend, para no depender de la consola del host.

---

## 3. Plan de Implementación (Checklist)

### Fase A — Investigación Funcional y Contratos (Backend)
- [x] Mapear el comportamiento real de `codex execute` cuando se le pasa un token vía `--context` vs cuando usa la caché local.
- [x] Levantar el backend con `ORCH_CODEX_ACCOUNT_MODE_ENABLED=true` y verificar en Swagger/UI.
- [x] Ejecutar prueba manual en consola: `codex login` en la máquina que corre GIMO y probar si GIMO (en `account` mode vacío o sin apiKey) logra orquestar exitosamente.

### Fase B — Diseño de Producto y UX (Frontend)
- [x] Definir la mejor UX en `ProviderSettings.tsx`:
  - **Opción Recomendada:** Si el backend detecta que falta autenticación, mostrar un botón en UI que inicie el flujo de *Device Code* (o equivalente si GIMO levanta el proxy OAuth), o bien dar instrucciones claras de ejecutar `codex login` en el terminal del servidor.
  - Mostrar estados claros: "Autenticado con Cuenta", "Requiere Login".
- [x] Limpiar los campos de texto redundantes si la autenticación se delega al CLI o al flujo de OAuth.

### Fase C — Desarrollo e Implementación
- [x] **Backend (`provider_auth_service.py` & `codex.py`):** 
  - Soportar el paso de sesión o tokens OAuth temporales al CLI.
  - Opcional pero recomendado: Endpoint `/ops/provider/codex/login` para iniciar el flujo `--device-auth` devolviendo la URL/código a la UI.
- [x] **UI (`ProviderSettings.tsx`):** 
  - Ocultar campo de API Key cuando se selecciona Account mode.
  - Añadir wizard/botón para conectar la cuenta.
- [x] **Test de Conexión:** Validar que el botón "Test Connection" devuelve errores específicos de "Sesión expirada" o "Requiere login interactivo" en lugar de errores crudos del CLI.

### Fase D — Entrega y QA
- [x] Tests unitarios y de integración para:
  - Persistencia del Provider sin secrets en texto plano.
  - Validación del capability update.
- [x] Documentar en un archivo `/docs/runbooks/codex-account-mode.md` (o similar) cómo activar y usar esta feature.
- [x] Evidencias de funcionamiento real (`docs/evidence/`).

---

## 4. Criterios de Aceptación (DoD)
1. Activada la flag `ORCH_CODEX_ACCOUNT_MODE_ENABLED`, la UI de GIMO muestra la opción de Account Mode para el provider Codex.
2. El usuario puede guardar la configuración sin introducir manualmente una API Key de OpenAI.
3. El proceso de autenticación es claro (sea mediante Device Flow embebido en la UI, o directrices UI explícitas sobre el CLI host).
4. El test de conexión es exitoso de extremo a extremo sin exponer tokens en la respuesta.
5. El sistema sobrevive a reinicios sin que se pierdan o expongan credenciales crudas.
6. Hay documentación operativa reproducible aportada en `/docs/`.

---

## 5. Riesgos a tener en cuenta
- **Comportamiento Opaco del CLI:** Depender del comando local `codex` implica que cualquier actualización del CLI que rompa el flujo de login podría romper la integración en GIMO.
- **Entornos Headless:** Si GIMO corre en Docker, la pre-autenticación interactiva en consola puede ser imposible si no se implementa el `--device-auth` expuesto a través de la interfaz web.
