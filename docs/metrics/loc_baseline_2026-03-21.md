# LOC Baseline — 2026-03-21

Backend: `tools/gimo_server/`

## Summary

| Metric | Value |
|--------|-------|
| Total files | 263 |
| Total LOC (non-blank, non-comment) | 35,359 |

## By Directory

| Directory | Files | LOC |
|-----------|-------|-----|
| services | 119 | 17,207 |
| routers | 33 | 4,356 |
| inference | 29 | 3,874 |
| __root__ | 11 | 2,104 |
| mcp_bridge | 8 | 2,034 |
| security | 12 | 1,791 |
| engine | 23 | 1,587 |
| adapters | 8 | 1,009 |
| models | 12 | 956 |
| providers | 6 | 306 |
| scripts | 2 | 135 |

## Files > 500 LOC

| File | LOC | Notes |
|------|-----|-------|
| mcp_bridge/manifest.py | 1,293 | Auto-generated |
| routes.py | 998 | Legacy — routers/legacy/ exists but migration incomplete |
| services/provider_service_impl.py | 751 | Candidate for future split |
| services/gics_client.py | 659 | GICS API client |
| services/skills_service.py | 624 | Skills management |
| services/custom_plan_service.py | 544 | Plan builder |
| services/observability_service.py | 513 | OTel integration |

## Monolith Split Results

| Original File | Before | After (shim) | Package |
|--------------|--------|-------------|---------|
| ops_service.py | ~1,008 | 6 lines | services/ops/ (8 files) |
| graph_engine.py | ~1,407 | 6 lines | services/graph/ (7 files) |
| provider_catalog_service_impl.py | ~1,048 | 4 lines | services/provider_catalog/ (7 files) |
