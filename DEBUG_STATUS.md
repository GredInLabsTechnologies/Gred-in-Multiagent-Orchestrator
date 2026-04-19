# GIMO Debug Mode Status

Systems currently in debug/bypass mode when `DEBUG=true`:

| System | Env Var | Effect |
|--------|---------|--------|
| **IntegrityVerifier** | `DEBUG=true` | Unsigned manifest accepted (fail-open) |
| **LicenseGuard** | `ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true` | License validation skipped |
| **ThreatEngine** | `DEBUG=true` | Escalation disabled — stays NOMINAL always |
| **Uvicorn** | `DEBUG=true` | Hot-reload enabled |
| **mDNS Advertiser** | `ORCH_MDNS_ENABLED=true` | OFF by default, separate from DEBUG |

## How to run in development

```bash
DEBUG=true ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true ORCH_HOST=0.0.0.0 python -m tools.gimo_server.main
```

## How to run in production

```bash
python -m tools.gimo_server.main
```

No env vars needed — all systems enforce strict mode by default.

## TODO (redesign needed)

- ThreatEngine is too aggressive for development (locks out after ~10 auth failures)
- IntegrityVerifier requires signed manifest which doesn't exist yet
- LicenseGuard blocks startup without bypass — needs dev license flow
- Consider a unified `GIMO_ENV=development|staging|production` flag
