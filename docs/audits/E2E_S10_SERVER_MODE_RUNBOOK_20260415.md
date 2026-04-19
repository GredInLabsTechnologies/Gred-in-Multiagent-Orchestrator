# E2E S10 Server Mode Runbook

> Companion to `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_FULL.md` rev 2.
> Use this runbook to validate server mode on the S10 (Android flagship)
> + a peer desktop, end-to-end, before declaring the feature ready.

## Vehicle

- **Host**: Samsung Galaxy S10 running the GIMO Mesh Android app (feature
  branch `feature/gimo-mesh`).
- **Peer**: Any desktop with `python -m tools.gimo_server.main` available
  and `ORCH_TOKEN` set to the same value as the S10 local core token.
- **Network**: Both devices on the same Wi-Fi SSID, no AP-isolation.

## Phase 0 — Pre-checks

1. `git rev-parse --abbrev-ref HEAD` returns `feature/gimo-mesh`.
2. `pytest tests/integration/test_boot_mesh_disabled.py tests/integration/test_server_mode_boot.py -q`
   → green.
3. S10 app version matches the branch (Settings → About → Version).
4. Desktop `zeroconf` installed: `pip show zeroconf`.

If any pre-check fails, stop — runbook is invalid until fixed.

## Phase 1 — S10 as server host

1. Open Settings → Hybrid Capabilities. Tap **Serve** pill, confirm it glows.
2. Open the foreground notification drawer. Confirm the notification title
   reads "GIMO Mesh — serving on LAN" and shows `Open http://<ip>:9325`.
3. Tap the notification. The default browser must open the dashboard and
   show the authenticated landing page (token pre-filled via deep link or
   prompted — either is acceptable, document which).
4. From the in-app Settings screen, confirm Local Host section reports:
   - Runtime: `ready`
   - LAN URL: `http://<ip>:9325` (not blank)
   - Web UI: non-empty

Record the exact LAN URL for Phase 2.

## Phase 2 — Desktop discovery

1. On the desktop, `export ORCH_TOKEN=<same token as S10 local core>`.
2. Run `gimo discover --timeout 8`.
3. Expected output: one verified row with MODE=`server`, HEALTH>0, name
   matching the phone's device_id.

If verification is `no`, the tokens diverged. Do not continue.

## Phase 3 — /ops/mesh/host cross-surface

1. `curl -H "Authorization: Bearer $ORCH_TOKEN" http://<s10-ip>:9325/ops/mesh/host`
2. Expected JSON keys:
   - `device.device_mode == "server"`
   - `lan_urls` contains the expected URL
   - `mdns_active == true`
   - `advertised_signals.mode == "server"`
3. Cross-check the same data via `gimo discover --json` — `mode`, `health`,
   `load` must match within one refresh cycle (≤60 s).

## Phase 4 — Dispatch self-penalty under load

Goal: prove the dynamic self-penalty from Cambio 2 actually fires.

1. Enroll a second Android (or any mesh device) with mesh_enabled=True so
   there is a viable alternative to the S10 host.
2. On the S10, drive CPU to >70 % (run a benchmark model inference).
3. Submit a dispatch request via the desktop peer. Observe the returned
   `DispatchDecision.device_id` — it must be the secondary device, not the
   S10 host. Re-run with the S10 idle — S10 becomes eligible again.
4. (Optional) Repeat with battery at ~25 % and cable unplugged — same
   expectation: dispatch avoids the S10 until it is plugged in or >30 %.

## Phase 5 — Graceful teardown

1. Tap Settings → Serve pill off.
2. Confirm:
   - Notification title returns to plain "GIMO Mesh".
   - `/ops/mesh/host` still returns the device but `mdns_active` is now
     `false` (because the runtime shut down the advertiser).
   - `gimo discover` on the desktop returns no peers within one scan window.

## Phase 6 — Report

Write the findings into
`docs/audits/E2E_IMPLEMENTATION_REPORT_20260415_SERVER_MODE_FULL.md`
under a "Runtime smoke — S10" section. Include:

- Exact LAN URL seen on S10.
- `gimo discover --json` output for one verified peer.
- `/ops/mesh/host` JSON body.
- Dispatch decision log (at least one idle and one loaded case).
- Any deviations from the expected behaviour, with severity per the E2E
  skill classification (BLOCKED_EXTERNAL / BLOCKER / CRITICAL / GAP /
  FRICTION / INCONSISTENCY / SILENT_FAILURE).

Do not sign the implementation report DONE until every phase above is
either PASS or explicitly documented as blocked by an external factor
outside the product's control.
