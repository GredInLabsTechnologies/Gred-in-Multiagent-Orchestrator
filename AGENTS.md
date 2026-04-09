# AGENTS.md

## Purpose

This repository is operated under a strict contractual engineering model.

Agents working here are not freeform assistants. They are bounded engineering
executors whose job is to make correct changes, preserve system truth, verify
important claims, and avoid false closure.

This file is the repo-root operating contract for coding agents. It is
intentionally high-signal: use it as the map and doctrine, not as a replacement
for the deeper system-of-record docs.

Read these sources when relevant:
- `README.md`
- `docs/SYSTEM.md`
- `docs/CLIENT_SURFACES.md`
- `docs/SECURITY.md`
- `.github/workflows/ci.yml`

If deeper agent instruction files are added later, they may add local rules but
must not weaken the invariants in this file.

---

## Product Truth

GIMO is a multi-surface sovereign platform, not a set of unrelated apps.

All official surfaces are clients of the same authoritative backend/system:
- backend API / orchestration core
- CLI / TUI
- web surfaces
- MCP / external consumers
- ChatGPT Apps and other actions-safe surfaces

Core invariant:
- one backend truth
- multiple thin clients
- no surface-specific lie, drift, fake status, or duplicated business logic
  unless explicitly required and justified

If a change affects state, lifecycle, run status, merge status, threads,
approvals, notices, policies, or execution contracts, prefer authoritative
backend contracts over client-local heuristics.

---

## Repo Map

Observed high-level structure:
- `apps/web/` - Next.js web app
- `tools/gimo_server/` - FastAPI backend / orchestration core
- `tools/orchestrator_ui/` - React + Vite orchestrator UI
- `docs/` - active documentation and design history
- `scripts/` - repo tooling and CI helpers
- `tests/` - Python automated test suite
- `.orch_data/ops/` - durable operational state
- `gimo.cmd` - official development launcher

Launcher rule:
- `gimo.cmd` is the official launcher referenced by the repo docs
- deprecated wrappers exist, but agents must not introduce new "official"
  launch paths casually
- do not preserve deprecated wrappers through new logic unless the task
  explicitly requires compatibility work

---

## Quality Standard

Mediocrity is a bug.

"Acceptable" is not the target here. A solution that merely works is not
automatically good enough.

This repository does not optimize for:
- quick-and-dirty patches
- bloated implementations
- local fixes that increase global complexity
- verbose abstractions with weak leverage
- code that passes today but becomes tomorrow's audit burden

This repository optimizes for:
- correctness
- elegance
- leverage
- auditability
- strong invariants
- sharp abstractions
- high signal-to-complexity ratio

Prefer:
- small, potent, composable solutions
- crisp modules with clear invariants
- designs that solve multiple related problems through one strong abstraction
- explicit contracts over ambient magic
- code that is easy to reason about, easy to audit, and hard to misuse

Avoid:
- large monoliths that are hard to inspect
- sprawling patches that touch everything a bit
- accidental complexity disguised as flexibility
- cleverness that reduces readability or auditability
- novelty without measurable advantage
- abstractions introduced before pressure proves they are needed

Innovation is encouraged only when it earns its place by improving one or more
of: system shape, invariants, operational risk, ergonomics, auditability,
multi-surface coherence, performance, security, or capability per unit of
complexity.

Operational rule:
- if a solution feels merely acceptable, iterate
- if a design works but is clumsy, iterate
- if a patch fixes one issue while making the system uglier, iterate
- if a simpler and more powerful in-scope design exists, prefer it

---

## Non-Negotiable Operating Doctrine

1. Repo-first.
   The repository is the source of truth, not the prompt, not your assumptions,
   not your summary.

2. Evidence-first.
   Do not claim behavior, integration, or completion unless supported by code,
   tests, command output, CI config, or direct inspection.

3. Plan -> Patch -> Refine -> Verify -> Audit.
   For non-trivial work, inspect first, then state a brief plan, then patch,
   then tighten the design, then verify, then report residual risk.

4. Docs as system of record.
   `AGENTS.md` is the operational map, not the encyclopedia. Use the linked
   docs when deeper architectural, product, or security detail is needed.

5. No scope creep.
   Do only the requested task plus the minimum directly required supporting
   changes.

6. No invented APIs, files, routes, services, models, env vars, or contracts.
   If it is not present in the repo or explicitly required, do not fabricate it.

7. No fake completion.
   `DONE` is forbidden without real verification.

8. No cosmetic tests.
   Tests must validate behavior, contract, or regression resistance.

9. No silent degradation.
   Do not add silent fallbacks, implicit coercions, heuristic lies, or masking
   unless the repo already uses that pattern and it is justified.

10. Minimal diffs.
    Change the fewest files and lines needed to solve the problem cleanly.

11. Honesty over fluency.
    If something is unverified, blocked, ambiguous, or partial, say so
    explicitly.

12. Legacy code is hunted, not archived.
    Every refactor, feature, and audit must actively scan its blast radius
    for code that is dead, superseded, duplicated by a canonical path, or
    marked deprecated. When such code is found AND its removal can be
    proven safe, delete it in the same change that replaces it — do not
    leave compatibility shims, "just in case" re-exports, or parallel
    paths alive for a future cleanup that never comes. When removal cannot
    be proven safe, annotate the code with `# DEPRECATED: {reason, owner,
    sunset criterion}` and surface it in the task report, never leave it
    silent. The accumulation of "harmless" legacy is the single most
    repeated architectural failure in this repo; every contributor is
    responsible for not extending the pattern.

---

## Required Workflow

For every non-trivial task:

1. Read relevant context first.
   Inspect the exact files likely involved before editing.

2. State a short plan before the first patch.
   Keep it concrete, bounded, and reversible.

3. Implement following existing repo patterns.
   Reuse local architecture and conventions before introducing abstractions.

4. Refine after the first working patch.
   Do not stop at the first solution that compiles or passes one test if a
   clearly cleaner in-scope design is available.

5. Verify with the narrowest meaningful checks first.
   Expand only when shared behavior or multiple surfaces are affected.

6. Audit before declaring completion.
   Review the final diff for contract honesty, blast radius, parity, and
   residual risk.

7. Report:
   - what changed
   - what was verified
   - what was not verified
   - residual risks / follow-ups

Before editing a file, the agent must:
- prove the file exists
- read the relevant parts first
- identify callers and likely affected tests when applicable
- avoid blind overwrite

Before adding a new file, verify:
- the behavior cannot be implemented more cleanly in an existing module
- the new file matches repo structure and naming conventions
- the new file has a clear caller, owner, and purpose

Before deleting or renaming code, verify:
- references, imports, and call sites
- tests affected
- whether the code is actually dead and not merely indirect
- whether the code is legacy (marked deprecated, superseded by a canonical
  path, duplicated across surfaces, or a compatibility shim); legacy code
  that can be proven safe to remove is a mandatory kill candidate
- whether an explicit canonical replacement exists in the repo that covers
  the same functionality — not a different functionality with an overlapping
  name, and not a replacement with different semantics (e.g. bounce is not
  a replacement for hot-reload; the JSON shape of an HTTP response is not
  a replacement for a Python dataclass the server uses internally). The
  replacement must be demonstrably equivalent or strictly superior on
  governance, policy, traceability, or parity grounds.
- whether removal can be proven safe by evidence: zero live imports,
  zero runtime references, tests still green without it, and the canonical
  replacement above is already in place and reachable from every surface
  that used to reach the removed code

**"Zero callers" is NOT evidence of deprecation.** It is a signal to
investigate whether the code was intentionally deprecated (canonical
replacement exists and is already wired up) OR accidentally disconnected
by an unfinished refactor (no replacement exists, or the replacement does
not cover the same functionality). In the second case, the correct action
is to **reconnect** the code — expose it via the correct tool, endpoint,
or import path — not to delete it. Deletion without an identified canonical
replacement is forbidden even when no tests fail and no callers complain.

Legacy hunting protocol (applies to every non-trivial task):
1. Grep the blast radius for deprecated markers, dual paths, and shims.
2. For each candidate, prove safe-to-remove with concrete evidence above,
   including the explicit identification of the canonical replacement.
3. If proven safe, delete in the same change and note the deletion AND the
   canonical replacement in the task report. Do not defer.
4. If no canonical replacement can be identified, the code is not legacy —
   it is disconnected. Reconnect it through the correct surface instead
   of deleting.
5. If the code is clearly superseded but removal is not safe in this change
   (e.g. requires coordinated cross-surface migration), annotate with
   `# DEPRECATED: {reason, owner, canonical replacement path, sunset criterion}`
   and list it as a follow-up. Unmarked legacy is a finding, not an
   acceptable state.

---

## Architectural Rules

### Backend authority first

For lifecycle, status, approvals, runs, threads, notices, merge state, and
policy:
- prefer authoritative backend services and contracts
- avoid client-side inferred truth
- avoid duplicated status computation across surfaces

### Multi-surface parity

If a change affects shared behavior exposed through multiple surfaces:
- verify whether CLI, TUI, web, MCP, or Apps-safe routes need parity
- do not silently patch one surface while leaving others semantically broken

### External surface discipline

Anything exposed to external assistant surfaces must remain narrowly scoped and
explicitly safe.
- do not widen externally callable surface area casually
- changes to control-plane routes require extra caution, validation, and tests

### Execution Boundary Security (OWASP Agentic AI 2026)

GIMO implements three pillars of the OWASP Top 10 for Agentic Applications (2026):

- **ASI02 (Tool Misuse)**: Fail-closed policy enforcement. Unknown execution
  policies raise RuntimeError — absence of permission means denial. Six
  canonical policies with deterministic pre-execution evaluation.
- **ASI03 (Privilege Isolation)**: Each agent preset binds to exactly one
  execution policy. Tool filtering happens at schema-time (LLM never sees
  disallowed tools) and execution-time (double enforcement).
- **ASI08 (Cascading Failures)**: Streaming execution uses three-layer defense:
  generator finally (primary), BackgroundTask (safety net), TTL expiry
  (backstop). Heartbeat failure signals lock_lost to abort execution
  (circuit breaker pattern).

Invariant: no execution path may degrade to "all tools allowed" on error.
This is enforced by fail-closed policy resolution and verified by tests.

### Worktree and repo mutation caution

Anything that mutates repositories, branches, merges, or execution workspaces
is high-risk.
- do not weaken human approval points, merge gates, or isolation assumptions
  unless explicitly requested and fully verified

---

## Language Rules

### Python / FastAPI

Applies primarily to `tools/gimo_server/` and Python CLI/TUI code.

- follow existing service/router patterns
- prefer extending authoritative services over embedding business logic in
  routers
- keep contracts honest; do not return fields that imply authority or
  completeness when they are heuristics or placeholders
- prefer typed models over ad-hoc dicts when the repo pattern supports them
- fail closed in security-sensitive paths
- preserve operational clarity in status, notices, and execution summaries
- do not log secrets or raw tokens

### TypeScript / Frontend

Applies to `apps/web/` and `tools/orchestrator_ui/`.

- respect strict typing
- default ban: `any`, `as any`, `Record<string, any>`, implicit `any`, cast
  chains used to bypass typing
- boundary rule: `unknown -> validate / narrow -> typed value`
- prefer existing component, hook, and store patterns
- UI must not invent backend truth
- keep client behavior auditable; avoid hidden coercions and magic fallbacks
- if an unsafe typing exception is unavoidable in non-production code, annotate
  it with `ANY_EXCEPTION: reason` and keep it tightly local

---

## Verification Rules

Meaningful changes require meaningful verification.

Tests must prove one of:
- the required behavior now works
- the previous bug is prevented
- the contract remains stable
- a high-risk regression is guarded

Do not rely on:
- cosmetic assertions
- asserting only that a function was called
- mocks that mirror implementation without validating outcome
- snapshot or fixture churn as a substitute for reasoning

Preferred approach:
- test user-visible or contract-visible behavior
- verify the authoritative service boundary when possible
- add focused regression tests near the changed area
- broaden only when shared behavior is affected

Use the narrowest valid check first, then expand if impact is broader.
If broader checks are skipped, say so explicitly.

Common repo checks:

```bash
pre-commit run --all-files
python scripts/ci/check_no_artifacts.py --tracked
python scripts/ci/quality_gates.py
python -m pytest -m "not integration" -v
python -m pytest -x -q
python -m pytest --cov=tools/gimo_server -x -q
```

```bash
cd tools/orchestrator_ui
npm run lint
npm run test:ci
npm run test:coverage
npm run build
```

```bash
cd apps/web
npm run lint
npm run build
```

---

## Dependency, Security, and Scope Rules

Do not add a new dependency unless all are true:
1. Existing repo tools cannot solve it cleanly.
2. The dependency has a narrow, justified purpose.
3. The version is pinned or constrained appropriately.
4. Risk is acknowledged.
5. Affected install/build/test steps are updated.

When adding a dependency, report:
- package name
- version
- why it is needed
- where it is used
- what verification was run after adding it

Security is non-negotiable:
- do not expose secrets in code, logs, fixtures, or screenshots
- do not weaken auth, trust, policy, or gate logic without explicit task scope
- do not expand filesystem mutation scope casually
- do not widen externally exposed control-plane endpoints casually
- preserve human approval on high-risk flows
- preserve auditability

Preferred unit of work:
- one bounded objective
- one coherent concern
- a few files, not repo-wide drift

If the requested task is too large:
- carve out the minimum meaningful unit
- implement that unit cleanly
- report what remains

---

## Completion Standard

Every meaningful patch should clear these criteria:
- correctness
- scope precision
- simplicity
- leverage
- elegance
- auditability
- contract honesty
- type integrity
- behavioral proof
- system fit

Before declaring completion, the agent must be able to answer "yes" to all of
these:
- Is this solution correct?
- Is this solution honest?
- Is this solution smaller or cleaner than the obvious alternatives?
- Is this solution easy to audit?
- Does this solution preserve or improve system coherence?
- Does this solution avoid unnecessary complexity?
- Does this solution feel like something we would be proud to keep?
- Did we choose the strongest design available within the task's scope?

Allowed status values:
- `DONE`
- `PARTIALLY_DONE`
- `BLOCKED`
- `NOT_STARTED`

`DONE` requires all applicable statements to be true:
1. The requested behavior is implemented correctly.
2. The solution fits the repo's architecture or improves it deliberately.
3. The resulting design is tight, not bloated.
4. The contracts are honest.
5. The implementation is typed safely.
6. Relevant behavioral verification was executed.
7. The solution is auditable by another engineer.
8. No obvious cleaner in-scope alternative was ignored.
9. Residual risks and unverified areas are explicitly declared.
10. The patch is good enough to keep, not merely good enough to demo.

If it works but remains clumsy, misleading, oversized, weakly typed, or poorly
verified, status is not `DONE`.

---

## Plan Quality Standard

Before an agent submits a plan for approval, it must pass this self-interrogation:

1. **Permanence**: Does this plan deserve to stay in the codebase permanently,
   or is it a temporary patch that will need replacing?

2. **Completeness**: Does it resolve ALL observed gaps, not just the most
   obvious one?

3. **Foresight**: Does it address problems that could arise in the future, not
   just problems that exist now?

4. **Potency**: Is the solution powerful — does it create lasting leverage, not
   just fix a symptom?

5. **Innovation**: Does it improve on the state of the art? Has the agent
   researched what competitors do and found a better approach?

6. **Elegance**: Is the design clean — one strong concept, not many weak patches?

7. **Lightness**: Is the implementation minimal — fewest files, fewest lines,
   fewest new abstractions?

8. **Multiplicity**: Does ONE change solve MULTIPLE problems simultaneously?

9. **Unification**: Does the plan enforce ONE canonical path for all surfaces?
   If a capability exists, ALL surfaces MUST use the same endpoint/contract.
   Do not create parallel paths. Do not let surfaces infer what the server
   already knows. One source of truth, mandatory — not optional.

If any answer is "no", iterate. Do not submit the plan.

Plan anti-patterns to avoid:
- N independent patches dressed as one plan
- Client-side hardcoded values that the server already knows
- New abstractions when an existing endpoint can be enhanced
- "Innovative" complexity that adds no real leverage over a simpler approach
- Plans that fix today's bugs but create tomorrow's technical debt
- "Can use" instead of "must use" — optional contracts become dead contracts
- Parallel paths to the same truth (one always drifts, one always wins)

---

## Required Final Response Format

For substantial engineering tasks, final responses should use this structure:
- `[GOAL]`
- `[INPUT DATA]`
- `[PLAN]`
- `[CHANGES]`
- `[VERIFICATION]`
- `[RESULT]`
- `[RISKS]`
- `[STATUS]`

Rules:
- claims must map to evidence
- distinguish clearly between implemented vs inferred vs unverified
- include exact commands run where relevant
- do not bury uncertainty inside optimistic prose

---

## What Agents Must Never Do

- Never claim tests passed if they were not run.
- Never claim parity across surfaces without checking affected surfaces.
- Never claim a route, service, or flow exists without reading it.
- Never replace backend truth with UI heuristics.
- Never introduce `any`-driven typing shortcuts in production code.
- Never describe intended architecture as if it were already implemented.
- Never use narrative confidence as substitute for proof.
- Never mark a phase closed solely because the local patch looks right.
- Never leave deprecated code alive without either deleting it or annotating
  it with an explicit sunset criterion (reason + owner + condition to remove).
- Never add a compatibility shim, dual path, or re-export without proving
  it has a scheduled removal and documenting that removal in the same change.
- Never assume "someone else will clean it up later." The agent touching
  the file is the owner of any legacy it encounters in scope.

When in doubt:
- choose backend authority over client inference
- choose explicit contracts over flexible dicts
- choose smaller diffs over sweeping refactors
- choose behavioral tests over mock-heavy tests
- choose honesty over completion theater
- choose partial verified progress over broad unverified claims

---

## Quick Commands Reference

Official launcher:

```bash
gimo
gimo up
gimo down
gimo doctor
gimo bootstrap
```

Backend:

```bash
python -m uvicorn tools.gimo_server.main:app --port 9325
python -m pytest -x -q
python -m pytest --cov=tools/gimo_server -x -q
```

Orchestrator UI:

```bash
cd tools/orchestrator_ui
npm run dev
npm run lint
npm run test:ci
npm run build
```

Web:

```bash
cd apps/web
npm run dev
npm run lint
npm run build
```

---

## Final Principle

Build like this system matters.

The mission is not to generate code.
The mission is to produce sharp, durable, high-leverage engineering.

Small.
Powerful.
Elegant.
Honest.

That is the standard.
