# GIMO — Gred In Multi-Agent Orchestrator

Orquestador multiagente local que coordina LLMs (Ollama, OpenAI, Anthropic) para ejecutar flujos de trabajo complejos con planificaci&oacute;n, aprobaci&oacute;n humana y trazabilidad completa.

## Features

- **Orquestaci&oacute;n multiagente** — Plan&rarr;Graph&rarr;Approve&rarr;Execute con control humano en cada paso
- **MCP Bridge** — Herramientas externas conectadas v&iacute;a Model Context Protocol
- **Soporte multi-proveedor** — Ollama (local), OpenAI, Anthropic, con cascade autom&aacute;tico entre tiers
- **Token Mastery** — Tracking de costos en tiempo real, presupuestos, alertas y recomendaciones de modelo
- **Cold Room Auth** — Licenciamiento local con nonce protection y sesi&oacute;n segura (HMAC cookies)
- **UI profesional** — React + Vite con grafo interactivo (ReactFlow), chat colapsable y 8 paneles funcionales
- **Trust & Policy Engine** — Circuit breakers, guardrails anti-inyecci&oacute;n y pol&iacute;ticas configurables
- **575+ tests** automatizados con pytest

## Quickstart

### Requisitos previos

- Python 3.11+
- Node.js 18+
- Ollama (opcional, para modelos locales)

### Opci&oacute;n 1: Launcher autom&aacute;tico (Windows)

```bash
GIMO_LAUNCHER.cmd
```

Genera el token, inicia backend y frontend, y abre el navegador.

### Opci&oacute;n 2: Manual

```bash
# 1. Instalar dependencias backend
pip install -r requirements.txt

# 2. Instalar dependencias frontend
cd tools/orchestrator_ui && npm install && cd ../..

# 3. Iniciar backend (puerto 9325)
python -m uvicorn tools.gimo_server.main:app --port 9325

# 4. Iniciar frontend (puerto 5173)
cd tools/orchestrator_ui && npm run dev

# 5. Abrir http://localhost:5173
```

### Variables de entorno

| Variable | Descripci&oacute;n | Default |
|---|---|---|
| `ORCH_TOKEN` | Token de autenticaci&oacute;n API | Auto-generado |
| `ORCH_PROVIDER` | Proveedor LLM (`ollama`, `openai`, `anthropic`) | `ollama` |
| `ORCH_MODEL` | Modelo por defecto | `qwen2.5-coder:7b` |
| `DEBUG` | Modo debug con reload | `false` |

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
tools/
  gimo_server/          # Backend FastAPI
    routers/            # Endpoints (ops, ui, auth)
    services/           # L&oacute;gica de negocio
    data/               # Pricing DB, schemas
  orchestrator_ui/      # Frontend React + Vite
    src/components/     # Componentes UI
    src/hooks/          # Custom hooks
docs/                   # Documentaci&oacute;n activa
scripts/                # Scripts de utilidad
tests/                  # Test suite
```

## License

Propietario — Gred In Labs
