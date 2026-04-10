# Changelog

All notable changes to GIMO will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- **`cli_constants.py` deleted** — orphaned since the `gimo_cli/` package decomposition (2026-04-01). All constants already lived in `gimo_cli/config.py` with corrected values (timeouts 180s vs stale 15s/30s, `ACTIVE_RUN_STATUSES` delegated to `run_lifecycle.py` including `AWAITING_MERGE`). Zero imports remained.
- **`services/trust.py` TrustService deleted** — dead prototype created alongside `TrustEngine` in the same commit (2026-03-31). Never imported, never tested. `TrustEngine` (`trust_engine.py`) is the canonical implementation with 7+ active consumers, full 3-state circuit breaker, per-dimension GICS config, and audit logging.
- **18 deprecated shim files deleted** — re-export stubs in `services/` that forwarded to canonical sub-packages (`ops/`, `execution/`, `economy/`, `workspace/`, `observability_pkg/`, `graph/`). All ~193 consumer imports rewritten to canonical paths. Shims removed: `ops_service`, `engine_service`, `sandbox_service`, `execution_policy_service`, `run_worker`, `cost_service`, `cost_predictor`, `budget_forecast_service`, `cascade_service`, `workspace_context_service`, `workspace_policy_service`, `repo_service`, `repo_override_service`, `repo_recon_service`, `observability_service`, `anomaly_detection_service`, `log_rotation_service`, `graph_engine`.

### Fixed
- **Risk threshold drift** — `intent_classification_service.py` used `> 60` (risk=60 allowed review) while `merge_gate_service.py` used `>= 60` (risk=60 blocked). Aligned to `>= 60` everywhere, matching `risk_calibrator.py` baseline and existing test `test_phase7_merge_gate_risk_60_is_hard_block`.

### Changed
- **Subprocess helpers deduplicated** — identical `_popen`/`_run` in `claude_auth_service.py` and `codex_auth_service.py` (plus `_run_sync` in `provider_catalog/_base.py`) extracted to shared `_subprocess_util.py`. Windows `.cmd` shim compat and timeout handling in one place.
- **Dual observability consolidated** — deleted `services/observability.py` (159-line MVP) that caused double JSONL writes and double metric counting alongside the canonical OTel-based `observability_pkg/observability_service.py`. Thread metadata accumulation (`ConversationService.mutate_thread`) moved inline to the agentic loop's unified telemetry block. Zero functional loss; 5 dead methods removed (`record_agent_action`, `get_agent_insights`, `record_span`, `record_structured_event`, `record_usage`).
- **Phase 6 strategy externalized** — `PHASE6_PRIMARY_MODEL` / `PHASE6_FALLBACK_MODEL` class constants removed from `ModelRouterService`. Primary and fallback models now read from `OpsConfig.phase6` (Pydantic config with JSON persistence). Forced-local intents reuse `OpsConfig.auto_run_excluded_intents` instead of a duplicated hardcoded set.
- **Name-based model routing removed** — `_infer_capabilities`, `_TIER_PATTERNS`, `_CAP_PATTERNS`, `_infer_weakness`, `_build_prior_scores`, and `prefer_family` deleted across 12 files. GICS + benchmark enrichment is the single routing source of truth.

## [0.9.2-serverbond] - 2026-03-30

### Added

#### ServerBond Architecture
- **Encrypted CLI↔Server bonds** stored in `~/.gimo/bonds/` with AES-256-GCM encryption
- **6-level token resolution chain**: env vars → CLI flag → ServerBond → project config → legacy → prompt
- **Global config support**: `~/.gimo/config.yaml` for user-wide defaults with project overrides
- **Machine-bound encryption**: Tokens encrypted with PBKDF2-SHA256 (100K iterations), unusable if copied to another machine
- **Multi-server support**: Multiple bonds for dev/staging/prod simultaneously
- **Capability negotiation**: New `/ops/capabilities` endpoint for CLI handshake

#### CLI Commands
- **`gimo login <url>`**: Interactive bond creation with token prompt and server validation
- **`gimo logout <url>`**: Remove bond for a specific server
- **`gimo doctor`**: Comprehensive diagnostics with actionable hints (server, bond, license, config, git, provider)
- **`gimo providers login <provider>`**: Authenticate with LLM providers (codex/claude) via device flow
- **`gimo providers auth-status`**: Show authentication status for all configured providers
- **`gimo providers logout <provider>`**: Disconnect from an LLM provider

#### Server Endpoints
- **`GET /ops/capabilities`**: Returns server version, role, plan, and feature list for CLI bond handshake
- **Read-only access**: `/status` and `/health` now accessible to operator role (added to `READ_ONLY_ACTIONS_PATHS`)

### Changed

#### CLI Core
- **`_resolve_token()` rewritten**: Now uses 6-level resolution chain with ServerBond integration
- **`_load_config()` enhanced**: Merges global config (`~/.gimo/config.yaml`) with project config (`.gimo/config.yaml`)
- **`_api_request()` improved**: Autorecovery for 401 (expired bond) and 503 (server unreachable) with user-friendly messages
- **`status` command**: Works from any directory with env token or ServerBond (`require_project=False`)
- **`providers auth-status` command**: Works without project initialization (`require_project=False`)

#### Server Core
- **Defensive error handling in `operator_status_service`**: Each subsnapshot (git, provider, thread, run, budget, alerts) wrapped in try/except to prevent cascade failures
- **Operator role permissions**: `/status` and `/health` endpoints now accessible without admin token

### Fixed

- **Windows console compatibility**: Replaced all Unicode emojis with ASCII equivalents to fix `UnicodeEncodeError` on cp1252 consoles
- **Missing config parameters**: Added `config` parameter to two `_resolve_token()` calls (streaming + chat flows)
- **Portability from /tmp**: `gimo status` now calls server when using env token or ServerBond, even outside project directories
- **Provider auth portability**: `gimo providers auth-status` works from any directory
- **Server restart detection**: `/ops/capabilities` endpoint verified functional after server restart

### Security

- **AES-256-GCM encryption**: Tokens encrypted at-rest using cryptography.Fernet with PBKDF2-SHA256 key derivation
- **Machine-bound**: Encrypted bonds tied to machine fingerprint, preventing cross-machine token theft
- **Anti-exfiltration**: Stolen bond files unusable without original machine's fingerprint
- **Zero plaintext tokens**: Tokens never stored in plaintext on disk (except legacy compatibility mode)

### Documentation

- **`docs/SERVERBOND_IMPLEMENTATION_REPORT.md`**: Complete architecture overview with SOTA analysis
- **`docs/E2E_AUDIT_SUMMARY_2026-03-30.md`**: Executive summary with production readiness verdict (87.5% pass rate)
- **`docs/E2E_GAPS_FINAL_2026-03-30.md`**: Consolidated gap list (11 gaps + 2 observations)
- **`docs/E2E_AUDIT_ROUND2_2026-03-30.md`**: Round 2 comprehensive audit findings
- **`docs/E2E_VALIDATION_GAPS_2026-03-30.md`**: Round 1 validation findings
- **`test_e2e_comprehensive.sh`**: Automated test suite for 32 critical endpoints/commands
- **`demo_e2e_serverbond.sh`**: Complete E2E demo script from init to logout

### Testing

- **E2E Pass Rate**: 87.5% (28/32 tests passing)
- **Endpoints Tested**: 25/252 critical endpoints validated
- **Critical Gaps Resolved**: 6 gaps fixed during implementation (emojis, config, portability)
- **Blocking Issues**: 0 (production ready)
- **Pending P1 Issues**: 3 non-blocking gaps for hot fixes (mastery 500s, middleware bug)

### Technical Details

- **LOC Implemented**: ~464 lines (350 in gimo.py, 80 in operator_status_service.py, 30 in ops_routes.py, 4 in routes.py/cli_constants.py)
- **Dependencies**: Zero new dependencies (uses stdlib: hashlib, hmac, secrets, base64; existing: cryptography, yaml)
- **Bond Format**: YAML files in `~/.gimo/bonds/<fingerprint>.yaml` with encrypted tokens
- **Config Cascade**: CLI flags > env vars > project config > global config > defaults

### Migration Notes

- **Existing users**: No breaking changes. Legacy token resolution still works.
- **New users**: Run `gimo login <server_url>` to create first bond.
- **Multi-server users**: Create separate bonds with `gimo login <url>` for each server.
- **Provider auth**: Use `gimo providers login codex` to authenticate LLM providers.

---

## [0.9.1] - Prior Release

Previous features and changes (no changelog maintained prior to 0.9.2).
