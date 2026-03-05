# 🔀 Plan de Migración: Unificación en Monorepo GIMO

> **Estado**: ✅ COMPLETADO
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
├── firebase.json               ← Consolidado (solo Firestore)
├── firestore.rules             ← Reglas producción (de gimo-web)
├── firestore.indexes.json      ← De gimo-web
├── .gitignore                  ← Merge de ambos repos
├── .env.example                ← Merge de ambos repos
├── GIMO_DEV_LAUNCHER.cmd       ← Actualizado (+web en puerto 3000)
└── README.md                   ← Unificado
```

## Fases

| # | Fase | Estado |
|---|------|--------|
| 0 | Backup + validación de ambos repos | ✅ |
| 1 | `git subtree add` de gimo-web como `apps/web` | ✅ |
| 2 | Consolidar configs (.gitignore, .env, firebase) | ✅ |
| 3 | Añadir job CI para web | ✅ |
| 4 | Actualizar launcher | ✅ |
| 5 | README unificado | ✅ |
| 6 | Verificación completa | ✅ |

## Verificación

- [x] `python -m pytest -x -q` → 575+ tests pasan
- [x] `cd apps/web && npm run build` → Build exitoso
- [x] `pre-commit run --all-files` → Sin errores
- [x] `git log --oneline apps/web/` → Historial preservado

