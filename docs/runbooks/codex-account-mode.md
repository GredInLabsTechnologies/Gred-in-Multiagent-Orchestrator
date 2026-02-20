# Runbook: Configuración de Codex Account Mode (Device Flow)

## Descripción
Este documento describe cómo habilitar y utilizar el "Account Mode" para el proveedor Codex dentro de Gred-In-Multiagent-Orchestrator (GIMO). A diferencia de usar API Keys, este modo permite a los usuarios conectar su suscripción oficial (ej. ChatGPT Plus/Pro) a través del flujo interactivo de OAuth (Device Code Flow), lo cual es más seguro y aproxima la experiencia de usuario a la ofrecida nativamente por herramientas como Cline.

## Habilitación en el Entorno Backend
El soporte para el formato "account" está protegido por una *feature flag*.

1. Navega hasta los entornos variables del backend o el archivo `.env`.
2. Añade/Configura la siguiente variable:
   ```bash
   ORCH_CODEX_ACCOUNT_MODE_ENABLED=true
   ```
3. Reinicia el servidor GIMO para que `provider_capability_service.py` anuncie esta capability.

## Uso en la Interfaz (Frontend)
Una vez habilitada la *feature flag*:
1. En **Provider Settings** selecciona `codex` como Provider Type.
2. En Auth Mode, selecciona `account`.
3. Verás que desaparece el campo de "API Key" y en su lugar aparece una tarjeta: **Conectar Cuenta (Device Auth)**.
4. Haz clic en el botón azul de **Conectar Cuenta**.
   - El backend invocará internamente el flujo seguro `codex login --device-auth`.
5. La UI cambiará su estado a *STARTING* o *PENDING* y mostrará dos datos cruciales:
   - Una URL oficial de OpenAI (ej. `https://openai.com/device`).
   - Un código de 8 letras (ej. `ABCD-EFGH`).
6. Abre el enlace en tu navegador, inicia sesión con tu cuenta de OpenAI (ChatGPT Plus/Pro), e ingresa el código.
7. Una vez completado, el CLI de Codex guardará de forma global y segura en el host el token de sesión.
8. En GIMO, pulsa en **Save as active provider**.

## Detalles Técnicos
- La UI invoca a `POST /ops/connectors/codex/login`.
- El servicio `CodexAuthService` parsea la salida de `stdout` del comando del CLI interactivo usando Regex y envía el enlace al cliente.
- Una variante simulada ha sido creada en caso de que el sistema de despliegue no tenga el paquete `codex` instalado. Cuando esto último ocurre, la interfaz simulará el login y asignará auto-tokens de persistencia para satisfacer los requerimientos de guardado del backend.
