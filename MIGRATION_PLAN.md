# 🔀 Plan de Migración: Unificación en Monorepo GIMO

> **Estado**: EN EJECUCIÓN
> **Fecha**: 2026-03-04
> **Este repo** se convierte en el monorepo unificado de GIMO.

## Objetivo

Fusionar `GIMO WEB` (landing + licencias, Next.js) en este repositorio para tener un solo monorepo.

## Principio: Mínima Invasión

- **NO se mueven** `tools/`, `tests/`, `docs/`, `scripts/`
- **NO se cambian** imports Python, Dockerfile, pyproject.toml
- **Solo se añade** `apps/web/` con el contenido de gimo-web
- **Se consolidan** configs compartidas (.gitignore, .env.example, firebase)

## Estructura Final

```
GIMO/
├── apps/
│   └── web/                    ← gimo-web importado aquí (git subtree)
├── tools/
│   ├── gimo_server/            ← Sin cambios
│   └── orchestrator_ui/        ← Sin cambios
├── tests/                      ← Sin cambios
├── docs/
├── scripts/
├── .github/workflows/ci.yml   ← +1 job para web
├── firebase.json               ← Consolidado
├── firestore.rules             ← Reglas producción (de gimo-web)
├── firestore.indexes.json      ← De gimo-web
├── .gitignore                  ← Merge de ambos repos
├── .env.example                ← Merge de ambos repos
├── GIMO_DEV_LAUNCHER.cmd       ← Actualizado (+web en puerto 3000)
└── README.md                   ← Unificado
```

## Fases

| # | Fase | Riesgo |
|---|------|--------|
| 0 | Backup + validación de ambos repos | Nulo |
| 1 | `git subtree add` de gimo-web como `apps/web` | Bajo |
| 2 | Consolidar configs (.gitignore, .env, firebase) | Bajo |
| 3 | Añadir job CI para web | Bajo |
| 4 | Actualizar launcher | Bajo |
| 5 | README unificado | Nulo |
| 6 | Verificación completa | Nulo |

## Verificación

- [ ] `python -m pytest -x -q` → 575+ tests pasan
- [ ] `cd apps/web && npm run build` → Build exitoso
- [ ] `pre-commit run --all-files` → Sin errores
- [ ] `git log --oneline apps/web/` → Historial preservado
