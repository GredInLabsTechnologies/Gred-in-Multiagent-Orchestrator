# Release process

**Status**: NEEDS_REVIEW
**Last verified**: N/A

This project must remain **UNRELEASED** until the maintainer explicitly declares v1.0.

## Intended workflow (to be validated)

- Run quality gates.
- Run full test suite.
- Run dependency audit (pip-audit).
- Validate Docker build.
- Execute LLM adversarial suites and archive metrics.

## Definition of Done for 1.0 (proposed)

1) Docs consistent with code:
   - ports/entrypoints/scripts aligned
   - OpenAPI reflects implemented endpoints
   - Operations + Security + Troubleshooting filled with verified steps
2) Evidence pack complete under `docs/evidence/`:
   - quality gates output
   - full pytest output
   - bandit + pip-audit results
   - docker build logs
   - UI build/lint/test logs
3) Version markers updated:
   - `tools/gimo_server/version.py`
   - `tools/gimo_server/openapi.yaml`
   - UI package version (if applicable)

## Reproducible commands (recommended)

Backend + tests:

```cmd
pip install -r requirements.txt
	python scripts\\ci\\quality_gates.py
python scripts\quality_gates.py
python -m pytest -q
bandit -c pyproject.toml -r tools scripts
pip-audit -r requirements.txt
```

UI:

```cmd
cd tools\orchestrator_ui
npm ci
npm run lint
npm run build
npm run test:coverage
```

Docker:

```cmd
docker build -t gred-orchestrator:local .
docker compose up --build
```
