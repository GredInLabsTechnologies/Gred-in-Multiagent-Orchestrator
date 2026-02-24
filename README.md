# GIMO — Gred In Multi-Agent Orchestrator

> Orquestador multiagente local con soporte para LLMs locales (Ollama) y cloud.

## Quickstart
1. `pip install -r requirements.txt`
2. `cp .env.example .env` → configurar token
3. `python -m uvicorn tools.gimo_server.main:app --port 9325`
4. `cd tools/orchestrator_ui && npm install && npm run dev`
5. Abrir http://localhost:5173

## Documentación
- [Arquitectura](docs/SYSTEM.md)
- [Instalación y Config](docs/SETUP.md)
- [API](docs/API.md)
- [Seguridad](docs/SECURITY.md)

## Tests
`python -m pytest -x -q`

## License
Propietario — Gred In Labs
