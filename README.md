# GIMO — Gred In Multi-Agent Orchestrator

Monorepo unificado de GIMO: orquestador multiagente + plataforma web de licencias y suscripciones.

## Features

- **Orquestaci&oacute;n multiagente** — Plan&rarr;Graph&rarr;Approve&rarr;Execute con control humano en cada paso
- **MCP Bridge** — Herramientas externas conectadas v&iacute;a Model Context Protocol
- **Soporte multi-proveedor** — Ollama (local), OpenAI, Anthropic, con cascade autom&aacute;tico entre tiers
- **Token Mastery** — Tracking de costos en tiempo real, presupuestos, alertas y recomendaciones de modelo
- **Cold Room Auth** — Licenciamiento local con nonce protection y sesi&oacute;n segura (HMAC cookies)
- **UI profesional** — React + Vite con grafo interactivo (ReactFlow), chat colapsable y 8 paneles funcionales
- **Trust & Policy Engine** — Circuit breakers, guardrails anti-inyecci&oacute;n y pol&iacute;ticas configurables
- **GIMO Web** — Landing, autenticaci&oacute;n Firebase, licencias y suscripciones Stripe
- **575+ tests** automatizados con pytest

## Quickstart (Windows portable)

### Requisitos previos

- Python 3.11+
- Node.js 18+
- Ollama (opcional, para modelos locales)

### Flujo recomendado: clone &rarr; 2 comandos

```bash
gimo bootstrap
gimo
```

> **`gimo.cmd` es el UNICO launcher de desarrollo oficial del repo.** Todos los dem&aacute;s scripts (`GIMO_DEV_LAUNCHER.cmd`, `up.cmd`, `bootstrap.cmd`, etc.) son wrappers deprecated que redirigen a `gimo.cmd`.

### Comandos

```bash
gimo               # levantar todo (= gimo up)
gimo down           # detener todo y liberar puertos
gimo doctor         # diagnostico del entorno
gimo bootstrap      # setup completo desde cero
gimo mcp            # MCP server standalone (puerto 8000)
gimo up --no-web    # sin apps/web
gimo up --backend-only  # solo backend
```

Dentro de `gimo up`, comandos interactivos:
- `r` &mdash; restart backend
- `rf` &mdash; restart frontend
- `ra` &mdash; restart todo
- `s` &mdash; ver estado
- `q` &mdash; apagar todo y salir

Cambios en Python se aplican autom&aacute;ticamente via `uvicorn --reload` (no necesitas reiniciar).

### Flujo manual (avanzado)

```bash
# 1. Instalar dependencias backend
pip install -r requirements.txt

# 2. Instalar dependencias frontend (Orchestrator UI)
cd tools/orchestrator_ui && npm install && cd ../..

# 3. Instalar dependencias web (GIMO Web)
cd apps/web && npm install && cd ../..

# 4. Iniciar backend (puerto 9325)
python -m uvicorn tools.gimo_server.main:app --port 9325

# 5. Iniciar frontend (puerto 5173)
cd tools/orchestrator_ui && npm run dev

# 6. Iniciar web (puerto 3000)
cd apps/web && npm run dev
```

### Variables de entorno

| Variable | Descripci&oacute;n | Default |
|---|---|---|
| `ORCH_TOKEN` | Token de autenticaci&oacute;n API | Auto-generado |
| `ORCH_PROVIDER` | Proveedor LLM (`ollama`, `openai`, `anthropic`) | `ollama` |
| `ORCH_MODEL` | Modelo por defecto | `qwen2.5-coder:7b` |
| `DEBUG` | Modo debug con reload | `false` |

Para variables de GIMO Web (Firebase, Stripe, licencias), ver `apps/web/.env.example`.

## Documentaci&oacute;n

- [Arquitectura del Sistema](docs/SYSTEM.md)
- [Instalaci&oacute;n y Configuraci&oacute;n](docs/SETUP.md)
- [Referencia API](docs/API.md)
- [Seguridad](docs/SECURITY.md)
- [Changelog](docs/CHANGELOG.md)

## Tests

```bash
# Suite completa (~37s)
python -m pytest -x -q

# Solo tests de costos/mastery
python -m pytest tests/services/test_cost_*.py -v

# Con cobertura
python -m pytest --cov=tools/gimo_server -x -q
```

## Estructura del proyecto

```
apps/
  web/                    # GIMO Web — Next.js (landing, licencias, Stripe)
    src/app/              #   App Router (pages + API routes)
    src/lib/              #   Firebase, Stripe, auth, entitlement
    src/components/       #   Componentes React
tools/
  gimo_server/            # Backend FastAPI (orquestador)
    routers/              #   Endpoints (ops, ui, auth)
    services/             #   L&oacute;gica de negocio (52+ servicios)
    security/             #   License guard, auth, trust engine
    data/                 #   Pricing DB, schemas
  orchestrator_ui/        # Frontend React + Vite (UI del orquestador)
    src/components/       #   Componentes UI
    src/hooks/            #   Custom hooks
docs/                     # Documentaci&oacute;n activa
scripts/                  # Scripts de utilidad
tests/                    # Test suite (575+ tests)
```

## License

Propietario — Gred In Labs
