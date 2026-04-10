# Changelog

Todos los cambios notables de GIMO se documentan aquí.

## [Unreleased]
- UI Masterplan fases 1.5-5 (graph rewrite, chat, overlays, polish)
- **feat**: terreno preparado para providers remotos `groq` y `cloudflare-workers-ai` en backend, CLI y UI
- **feat**: `gimo providers add` registra providers sin activarlos y `gimo providers login --api-key` ya no cambia el provider activo
- **feat**: **Context Budget System** — el agentic loop se adapta automáticamente a providers con límites de tokens bajos (Groq free 6K, Cloudflare 4K, Ollama small models)
  - Auto-descubrimiento por headers (`x-ratelimit-limit-tokens`) y recovery de 413
  - Model Context Registry (`.orch_data/ops/model_context_registry.json`) — agentes auto-reportan su capacidad
  - Constrained mode: tool compaction, message trimming (sliding window), tool result cap
  - REST: `GET/PUT /ops/models/context-limits`
  - MCP: `gimo_register_model_context_limit`, `gimo_get_model_context_limits`
  - Flag `context_too_small` con hint diagnóstico para agentes que no conocen el loop
  - Modelos grandes (Claude, GPT-4o, Gemini) no se ven afectados (`is_constrained = budget <= 8192`)
- **fix**: Cloudflare Workers AI devuelve `content` como dict/list — normalizado en `openai_compat.py`
- **fix**: `openai_compat.py` captura `x-ratelimit-limit-tokens` de headers para auto-discovery
- **docs**: `docs/CONTEXT_BUDGET_SYSTEM.md` — arquitectura completa del sistema de presupuesto de contexto
- **docs**: runbook operativo para alta, credenciales y uso agentic de Groq + Cloudflare Workers AI

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
