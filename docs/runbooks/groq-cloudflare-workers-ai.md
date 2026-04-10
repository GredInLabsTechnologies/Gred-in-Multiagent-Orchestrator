# Runbook: Groq + Cloudflare Workers AI en GIMO

## Objetivo
Este documento deja trazado el alta operativa de `groq` y `cloudflare-workers-ai` como providers remotos para GIMO, con enlaces oficiales y el contrato real que el backend, la UI y el CLI esperan hoy.

Verificado contra documentación oficial el **10 de abril de 2026**.

## Confirmación de compatibilidad agentic

### Groq
- GIMO enruta `groq` por su adaptador OpenAI-compatible (`chat/completions`) y el loop agentic ya soporta tool calls.
- Groq documenta compatibilidad con clientes OpenAI usando `base_url=https://api.groq.com/openai/v1`.
- Groq documenta `Tool Use` / function calling, que es el requisito clave para que GIMO pueda ejecutar herramientas dentro del flujo agentic.

Enlaces oficiales:
- [Groq OpenAI Compatibility](https://console.groq.com/docs/openai)
- [Groq Tool Use Overview](https://console.groq.com/docs/tool-use/overview)
- [Groq Quickstart](https://console.groq.com/docs/quickstart)
- [GroqCloud Plans](https://groq.com/groqcloud)

### Cloudflare Workers AI
- GIMO usa el mismo patrón OpenAI-compatible (`chat/completions`) para este provider.
- Cloudflare documenta un endpoint OpenAI-compatible en `/v1/chat/completions` y una `baseURL` con el `account_id` embebido.
- Cloudflare documenta modelos con `Function calling`, suficientes para flujo agentic.
- El catálogo de Workers AI es `account-scoped`. GIMO no inventa un `/models` global: usa la API REST oficial `GET /accounts/{account_id}/ai/models/search` cuando hay token y `base_url` válidos.

Enlaces oficiales:
- [Workers AI OpenAI-compatible endpoints](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/)
- [Workers AI REST API getting started](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
- [Workers AI models catalog](https://developers.cloudflare.com/workers-ai/models/)
- [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Cloudflare Create API token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)

## Contrato CLI actualizado
- `gimo providers add ...` registra o actualiza un provider entry y **no** lo activa salvo que se pase `--activate`.
- `gimo providers login ... --api-key ...` guarda credenciales sobre un provider ya existente y **no** cambia `active`.
- `gimo providers set ...` sigue siendo la operación explícita para activar un provider.

## Activación rápida en GIMO

### Groq
1. Crea la cuenta y la API key:
   - [Groq Quickstart](https://console.groq.com/docs/quickstart)
   - [GroqCloud](https://groq.com/groqcloud)
2. Exporta la credencial si quieres aprovechar el atajo CLI:
   ```bash
   set GROQ_API_KEY=tu_api_key
   ```
3. Registra el provider sin cambiar el activo actual:
   ```bash
   gimo providers add groq-main --type groq --api-key tu_api_key
   ```
4. Si el provider ya existe y solo quieres guardar o rotar la key:
   ```bash
   gimo providers login groq --api-key tu_api_key
   ```
5. En la UI:
   - Provider Type: `groq`
   - Auth Mode: `api_key`
   - Base URL: opcional. GIMO ya usa `https://api.groq.com/openai/v1` por defecto.
6. Modelos recomendados hoy en GIMO:
   - `qwen/qwen3-32b`
   - `openai/gpt-oss-120b`
   - `openai/gpt-oss-20b`
   - `moonshotai/kimi-k2-instruct-0905`

### Cloudflare Workers AI
1. Activa Workers AI en tu cuenta:
   - Está incluido en Workers Free y Workers Paid.
   - La documentación oficial indica una asignación gratuita de `10,000 Neurons/day`.
2. Obtén token y `account_id` desde Workers AI:
   - Ve a [Workers AI](https://dash.cloudflare.com/?to=/:account/workers/ai)
   - Sigue el flujo `Use REST API` -> `Create a Workers AI API Token`
   - Si no usas la plantilla, Cloudflare indica que el token debe tener `Workers AI - Read` y `Workers AI - Edit`
3. Exporta la credencial si quieres aprovechar el atajo CLI:
   ```bash
   set CLOUDFLARE_API_TOKEN=tu_api_token
   ```
4. Registra el provider sin cambiar el activo actual:
   ```bash
   gimo providers add cloudflare-workers-ai-main --type cloudflare-workers-ai --base-url https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1 --api-key tu_api_token
   ```
5. Si el provider ya existe y solo quieres guardar o rotar la key:
   ```bash
   gimo providers login cloudflare-workers-ai-main --api-key tu_api_token --base-url https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1
   ```
6. Configura en GIMO:
   - Provider Type: `cloudflare-workers-ai`
   - Auth Mode: `api_key`
   - Base URL: `https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1`
7. Modelos recomendados hoy en GIMO:
   - `@cf/qwen/qwen3-30b-a3b-fp8`
   - `@cf/qwen/qwen2.5-coder-32b-instruct`
   - `@cf/openai/gpt-oss-120b`
   - `@cf/openai/gpt-oss-20b`
   - `@cf/moonshotai/kimi-k2.5`

## Estado del soporte en el repositorio

### Groq
- Tiene tipo canónico propio.
- Usa el adaptador OpenAI-compatible existente.
- Tiene `base_url` por defecto.
- Tiene catálogo curado actualizado para coding/agentic.
- El CLI acepta `GROQ_API_KEY`.

### Cloudflare Workers AI
- Tiene tipo canónico propio: `cloudflare-workers-ai`.
- Usa el adaptador OpenAI-compatible existente para ejecución.
- **No** tiene `base_url` por defecto porque el endpoint depende de `account_id`.
- La validación y el catálogo usan la API REST oficial de Cloudflare cuando hay credenciales válidas.
- El CLI acepta `CLOUDFLARE_API_TOKEN`.
- La UI muestra una guía explícita del endpoint y deja visibles las opciones avanzadas al seleccionar este provider.

## Notas de diseño
- `groq` encaja de forma natural en el flujo agentic de GIMO porque expone OpenAI-compatible y tool use.
- `cloudflare-workers-ai` también encaja, pero su contrato operativo correcto es distinto: el endpoint y el catálogo son por cuenta. Por eso GIMO exige `base_url` explícito y no inventa un default.
- El objetivo de este cambio es dejar ambos providers integrables en el pool remoto sin añadir rutas paralelas ni heurísticas de cliente.
