# Changelog

Todos los cambios notables de GIMO se documentan aquí.

## [Unreleased]
- UI Masterplan fases 1.5-5 (graph rewrite, chat, overlays, polish)

## [0.12.0] — 2026-03-04
- **feat**: Unificación monorepo — `apps/web/` (GIMO Web) fusionado via git subtree
- **feat**: Sistema completo de gestión de providers (UI + backend), catálogo, capability matrix
- **feat**: Auth por cuenta (device flow) para Codex y Claude
- **feat**: CI job `web / lint-build` para GIMO Web
- **feat**: Dependabot para `apps/web`
- **refactor**: Limpieza post-merge (archivos basura, firebase.json, .gitignore)
- **docs**: Documentación actualizada al estado actual del monorepo

## [0.11.0] — 2026-03-01
- **feat**: UI Masterplan fase 0-1 (zustand, framer-motion, sidebar/menubar/statusbar redesign)
- **feat**: Design tokens y glassmorphism system
- **refactor**: App.tsx migrado de 18 useState a zustand store

## [0.10.0] — 2026-02-28
- Completadas fases pendientes del REPO_MASTERPLAN (4, 6.3, 7)
- Documentaci&oacute;n consolidada de 10 &rarr; 7 archivos activos

## [0.9.2] — 2026-02-27
- **feat**: Componentes UI del orquestador multiagente (login, workflow, agents, evals)
- **feat**: Router de autenticaci&oacute;n con sesi&oacute;n httpOnly cookies
- **test**: Tests unitarios para nuevos componentes

## [0.9.1] — 2026-02-26
- **feat**: Security overhaul — Cold Room licensing, nonce protection, UI security dashboard
- **feat**: Firebase SSO profile + auth graph background styling
- **fix**: Unificaci&oacute;n de idioma UI a espa&ntilde;ol, imports no usados removidos

## [0.9.0] — 2026-02-23
- **milestone**: E2E funcional — plan &rarr; graph &rarr; approve &rarr; execute v&iacute;a Qwen
- **feat**: MCP bridge operativo
- **refactor**: REPO_MASTERPLAN fases 0-3, 5, 5.5 completadas
- **refactor**: Consolidaci&oacute;n de scripts (50+ &rarr; 15)
- **refactor**: Documentaci&oacute;n consolidada (67 &rarr; 8 archivos)
- **refactor**: Purga de archivos basura, m&oacute;dulos legacy eliminados
- **feat**: Anti-agent guardrails, endpoint `/ui/plan/create`
- **fix**: Port-based process killer para Windows zombie prevention
- **test**: 575+ tests passing (~37s)

## [0.8.0] — 2026-02-20
- **feat**: Prompt-injection security guards (dual pattern matching)
- **feat**: GPT Actions gateway hardened con pipeline de 3 fases
- **feat**: Core GIMO server con configuraci&oacute;n comprehensiva, licenciamiento, rutas API con SSE
- **feat**: Componentes UI fundacionales
