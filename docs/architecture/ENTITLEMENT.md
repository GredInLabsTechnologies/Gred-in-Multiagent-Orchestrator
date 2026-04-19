# Entitlement — Architectural Note

**Status**: web-surface-only by design (2026-04-19)
**Source**: `apps/web/src/lib/entitlement.ts`
**Audit context**: response to finding F7 of the Relaxed-Edison audit

## What exists today

License entitlement logic lives in the Next.js web app (`apps/web/src/lib/entitlement.ts`).
It runs in the server runtime (API routes, server components) and reads/writes Firestore
via `firebase-admin`. The algorithm:

1. Revoked license → deny + deactivate activations
2. Lifetime license → check status only
3. Non-lifetime license expired → deny
4. No subscription → deny
5. Subscription not active/trialing → deny
6. Subscription period expired → deny
7. Otherwise → allow

## Why this is not in the Python backend

The audit flagged this as a "client-side entitlement" concern (F7), under the
assumption that the logic should be centralized so CLI/MCP can reuse it.

Two facts make immediate extraction the wrong call:

1. **Licenses gate landing-page token emission, not runtime ops.**
   The CLI, TUI, and MCP bridge operate against `ORCH_TOKEN` (or session cookie).
   They never need to check license state to decide if a command runs. License
   status is checked *once* when the user requests a token from the web app.
   No current surface besides `apps/web` has a use case for entitlement.

2. **AGENTS.md §Quality Standard: "abstractions introduced before pressure
   proves they are needed"** are an explicit anti-pattern. Porting to Python
   would require `firebase-admin` in the backend (~100MB, Google SDK, service
   account JWTs). That cost has to be justified by at least one real consumer.

## When this changes

**Trigger for extraction**: the moment a non-web surface (CLI, MCP, Agent SDK,
new App façade) needs to verify license state to decide behavior.

**Migration path** (pre-designed, not implemented):

1. Pure evaluator → `tools/gimo_server/services/entitlement_service.py`
   - Input: serialized license + subscription records
   - Output: `EntitlementDecision` (frozen Pydantic model)
   - No I/O, no Firestore — it's arithmetic on supplied state
2. REST endpoint → `POST /ops/entitlement/evaluate`
   - Accepts `{license, subscription}` payload, returns `EntitlementDecision`
3. MCP tool → `gimo_evaluate_entitlement`
4. Web `entitlement.ts` replaces local `evaluateLicenseEntitlement` with HTTP
   call to the backend endpoint. Firestore writes (`setLicenseStatus`,
   `deactivateActiveActivations`) stay in web — they're the side-effect layer.

This split keeps the **decision** backend-canonical while the **persistence**
stays in the surface that owns the Firestore credentials, cleanly aligned with
AGENTS.md §"Backend authority first" without over-abstracting today.

## Why not extract now anyway

Per AGENTS.md §Legacy Hunting:
> "disconnected ≠ dead. Reconnect through the correct surface instead
> of deleting."

And:
> "the new file has a clear caller, owner, and purpose"

A hypothetical caller is not a clear caller. Building the shared service now
means it's untested by real traffic and we commit to keeping it in sync with
the single (web) consumer — a parallel-path anti-pattern.

The honest posture: **annotate the scope**, document the trigger and the
migration path, and extract the day a second consumer arrives. Not before.
