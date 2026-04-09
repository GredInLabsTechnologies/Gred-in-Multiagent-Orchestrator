# Peer Review Package — MCP Bridge Honest Cleanup

- **Commit under review**: `291f48a` on `main`
- **Date**: 2026-04-09
- **Author (implementer)**: Claude (Opus 4.6, Claude Code session)
- **Scope**: `tools/gimo_server/mcp_bridge/native_tools.py` + `AGENTS.md` §12 refinement
- **Reviewer**: independent agent, no prior context from implementer's session

You are reviewing this change with fresh eyes. The implementer may have missed something; your job is to find it. Do NOT trust the implementer's conclusions — verify every claim against the repo.

---

## 1. Objective of the change

Apply findings F-02 and F-09 from the R21 dual peer audits (Codex + Claude Sonnet) to the MCP native tools layer. The audits both independently concluded that `tools/gimo_server/mcp_bridge/native_tools.py` contained:

- Tools that **invented** backend state instead of consuming canonical sources (F-09: `gimo_get_status` probing sockets and synthesizing a `"RUNNING"/"STOPPED"` string instead of calling `OperatorStatusService.get_status_snapshot()`).
- A second orchestrator implementation (F-02: `_generate_plan_for_task` with its own LLM prompt and fallback, parallel to `/ops/generate-plan`).
- A launcher implementation duplicating the canonical lifecycle authority at `gimo_cli.commands.server` (F-01: `gimo_start_engine` forking uvicorn, vite, and minting its own ORCH_TOKEN).
- Direct state mutation from the client surface (`gimo_reload_worker` hot-reloading a module and mutating `server._active_run_worker`).
- Diagnostic introspection of the bridge process (`gimo_get_server_info`).

The change was further shaped mid-implementation by user feedback that refined the operating definition of "legacy" code (see §5), causing several delete → restore cycles. The final commit reflects the corrected approach, not the initial cut.

---

## 2. Exact changes

### 2.1 `tools/gimo_server/mcp_bridge/native_tools.py`

| Tool | Action | Rationale to verify |
|---|---|---|
| `gimo_get_status` | REWRITE | Thin wrapper over `OperatorStatusService.get_status_snapshot()`. No socket probe, no Ollama ping, no synthesized string. Returns `json.dumps(snapshot, indent=2, default=str)`. |
| `gimo_start_engine` | REWRITE as thin trampoline | Delegates to `gimo_cli.commands.server.start_server(host, port)`. Reuses `_server_url`, `server_healthy`, `_health_details`, `DEFAULT_SERVER_HOST`, `DEFAULT_SERVER_PORT` from the canonical launcher module. Returns JSON `{status, url, pid, version}`. No subprocess spawn, no `secrets.token_hex`, no `.env` writes, no vite. |
| `gimo_stop_engine` | NEW (symmetric to start_engine) | Thin trampoline over `gimo_cli.commands.server` helpers: `_kill_all_on_port`, `_wait_for_server_down`, `server_healthy`, `_find_pids_on_port`. Returns JSON `{status, url, down_state, listeners_found, listeners_killed}`. |
| `_generate_plan_for_task` | DELETE | Private function (no `@mcp.tool()`), zero live callers, superseded by `tools/gimo_server/routers/ops/plan_router.py::generate_plan` at `/ops/generate-plan`. |
| `gimo_reload_worker` | RESTORE gated by `GIMO_DEV_MODE` | Originally deleted as single-authority violation. Restored per revised AGENTS.md §12: no canonical replacement with equivalent semantics (bounce ≠ hot-reload). Registered only when `os.environ.get("GIMO_DEV_MODE")` is truthy. Risks (`importlib.reload` state corruption, race conditions) documented in the docstring. |
| `gimo_get_server_info` | RESTORE | Originally deleted as "internal diagnostics". Restored per revised AGENTS.md §12: no canonical replacement exists (backend cannot introspect its own Python import cache from outside its process). Read-only, no authority violation. |
| `gimo_chat` | LEFT AS-IS | The `_BACKGROUND_CHAT_TASKS` fire-and-return pattern is justified MCP glue: the agentic loop can take minutes (5–20 min for complex tasks), while MCP client timeouts are finite (inspected defaults: 30s general / 300s SSE; `ClientSession` does not fix a read timeout by default). The exact threshold depends on the specific MCP client and transport, but ANY fixed timeout is exceeded by long agentic loops. Future cleanup requires a backend-side async dispatch endpoint — out of scope. **NOTE (post-review correction):** the original claim of "~60s" was an unverified hypothesis; the actual library defaults found by the peer reviewer are listed above. The justification holds on the same logic (loop duration >> client timeout) but with corrected evidence. |
| All other tools (16) | UNCHANGED | No touches. |

### 2.2 `AGENTS.md` §12 refinement

The "Before deleting or renaming code" section of the Required Workflow was expanded with:

1. An explicit criterion: **"whether an explicit canonical replacement exists in the repo that covers the same functionality — not a different functionality with an overlapping name, and not a replacement with different semantics"**, with "bounce vs hot-reload" and "HTTP response JSON shape vs internal Python dataclass" given as examples.
2. A new bold rule: **"Zero callers is NOT evidence of deprecation. It is a signal to investigate whether the code was intentionally deprecated (canonical replacement exists and is wired up) OR accidentally disconnected by an unfinished refactor (reconnect, do not delete)."**
3. A new step 4 in the Legacy hunting protocol: **"If no canonical replacement can be identified, the code is not legacy — it is disconnected. Reconnect it through the correct surface instead of deleting."**

These clarifications were added in direct response to the implementer's initial over-deletion of `gimo_get_server_info` and `gimo_reload_worker`, which the user correctly identified as violating the spirit of the doctrine.

### 2.3 Diff stats

```
 AGENTS.md                                    |  39 ++-
 tools/gimo_server/mcp_bridge/native_tools.py | 410 +++++++++++++++------------
 2 files changed, 266 insertions(+), 183 deletions(-)
```

Net: **+83 lines** (deletions dominated by the original `gimo_start_engine` 72-line self-forking body + `_generate_plan_for_task` 50 lines; additions dominated by honest restoration docstrings, the new `gimo_stop_engine` tool, and the §12 refinement).

---

## 3. Verification evidence (what the implementer claims works)

Before accepting any of these as proof, re-run them yourself. Do not trust the implementer.

| Check | Command | Expected outcome | Claimed outcome |
|---|---|---|---|
| AST parse | `python -c "import ast; ast.parse(open('tools/gimo_server/mcp_bridge/native_tools.py', encoding='utf-8').read())"` | No exception | SYNTAX OK, 931 lines |
| Tool count, gate off | Import `native_tools`, `register_native_tools(FastMCP('t'))`, count tools with `GIMO_DEV_MODE` unset | 22 tools, `gimo_reload_worker` NOT in list, `gimo_get_server_info` IN list | 22 tools, reload_worker=False, server_info=True |
| Tool count, gate on | Same as above with `GIMO_DEV_MODE=1` | 23 tools, both present | 23 tools, reload_worker=True, server_info=True |
| Conformance tests | `python -m pytest tests/conformance/ -q --timeout=60` | All pass, no regressions | 8 passed |
| Unit tests (affected) | `python -m pytest tests/unit/ -k "mcp_bridge or native_tools or manifest" -q --ignore=tests/unit/test_adapters.py --ignore=tests/unit/test_openai_compat_adapter.py` | All pass | 17 passed |
| HTTP/MCP parity smoke | `curl -H "Authorization: Bearer $T" http://127.0.0.1:9325/ops/operator/status` + in-process call to `gimo_get_status` | Same top-level keys in both responses | Same 12 keys verified: `backend_status, backend_version, repo, branch, dirty_files, active_provider, active_model, workspace_mode, orchestrator_authority, last_thread, last_turn, active_run_id` |
| Server restart + health | `python gimo.py down && python gimo.py up` then `curl /health` | 200 | pid=31072, v=UNRELEASED, /ready=200 |

**Preexisting failures (NOT introduced by this change)**:
- `tests/unit/test_adapters.py` and `tests/unit/test_openai_compat_adapter.py` fail to collect due to missing `respx` Python module. These files were not touched by this commit and were already broken on `main` prior to this work. Excluded from the run.
- Cross-pollution between `tests/unit/` and `tests/conformance/` when run in the same pytest invocation causes `test_mcp_context_draft_is_cognitive_agent` to fail sporadically. Documented in `memory/MEMORY.md` as a preexisting `TestClient` issue. Running the suites separately is green.

---

## 4. Things you should independently verify

### 4.1 Does `gimo_get_status` actually return canonical state?

1. Start the server: `python gimo.py up`
2. Import and invoke the tool in-process:
   ```python
   import asyncio, json
   from tools.gimo_server.mcp_bridge import native_tools
   from mcp.server.fastmcp import FastMCP
   mcp = FastMCP('peer-review')
   native_tools.register_native_tools(mcp)
   mgr = getattr(mcp, '_tool_manager', None) or getattr(mcp, 'tool_manager', None)
   tools = getattr(mgr, '_tools', None) or getattr(mgr, 'tools', {})
   fn = getattr(tools['gimo_get_status'], 'fn', None)
   print(asyncio.run(fn()))
   ```
3. Fetch `/ops/operator/status` directly via curl with the bearer token.
4. **Verify**: the two responses must agree on the top-level keys. Any key in one that is missing in the other is a bug. Do NOT require literal byte equality — `default=str` in the JSON dump may change serialization of some values — but the key set must match.

### 4.2 Does `gimo_start_engine` actually delegate to the canonical launcher?

1. Stop the server: `python gimo.py down`
2. Grep the new `gimo_start_engine` body for any subprocess call or token generation — it should only contain imports from `gimo_cli.commands.server` and calls to `start_server()`, `server_healthy()`, `_health_details()`, `_server_url()`. **No `subprocess.Popen`, no `secrets.`, no file writes**.
3. Invoke it in-process (same pattern as 4.1) and verify the backend comes up via the canonical lifecycle authority at `gimo_cli.commands.server.start_server` (`server.py::start_server`). You can `monkeypatch` `start_server` and verify the trampoline calls it. The official user-facing launcher is `gimo.cmd` → `python -m gimo_cli` → this same function. `scripts/dev/launcher.py` is the pre-GPT-5.4 legacy path, now superseded.

### 4.3 Does the `GIMO_DEV_MODE` gate actually gate?

1. `unset GIMO_DEV_MODE`
2. Import `native_tools` fresh (`del sys.modules[...]`), register, enumerate tools. `gimo_reload_worker` **must not** appear.
3. `export GIMO_DEV_MODE=1`
4. Import fresh again, register, enumerate. `gimo_reload_worker` **must** appear.
5. Verify the gate accepts `1`, `true`, `yes`, `on` (case-insensitive) and rejects `0`, empty string, unset, and arbitrary strings like `maybe`.

### 4.4 Does `gimo_stop_engine` actually use the canonical shutdown?

1. Grep the new `gimo_stop_engine` body. It should import only from `gimo_cli.commands.server` and call `_kill_all_on_port`, `_wait_for_server_down`, `server_healthy`, `_find_pids_on_port`. **No direct `os.kill`, no PID file parsing, no raw socket probes**.
2. The return dict must include both `listeners_found` and `listeners_killed` counts.
3. Attempt a `stop → start → stop` cycle via the in-process pattern and verify each call returns the expected shape.

### 4.5 Is `_generate_plan_for_task` really dead code that was correctly superseded?

This is the claim most worth double-checking because the implementer's initial reasoning ("zero callers = delete") was explicitly flagged by the user as incorrect, and the implementer then re-justified the deletion under the corrected rule.

1. `grep -rn "_generate_plan_for_task" --include="*.py"` on the current checkout (exclude `*.md` because prior audit reports in `docs/audits/` will mention the function name). The grep should return **zero Python callers** — no import, no invocation, no test reference. Any live Python caller would mean the deletion was a regression.
2. Verify that `/ops/generate-plan` in `tools/gimo_server/routers/ops/plan_router.py::generate_plan` handles the same use case: generating a structured `OpsDraft` from a free-text prompt. Confirm it goes through validation and `audit_log` (the policy gate is at the `create_draft` layer via `_evaluate_draft_intent` called from `plan_router.py::create_draft` (~L81), not in the `generate_plan` endpoint directly — the peer reviewer correctly identified this). The deleted function (`_generate_plan_for_task`) did not go through ANY of these checks, so `/ops/generate-plan` is strictly superior even without an inline policy gate.
3. Check the R17.1 commit history: `git log --all --oneline --grep="R17.1"`. The commit should show that `gimo_generate_team_config` was rewritten at that point to delegate to `/ops/generate-plan`, which is the template the current cleanup claims to follow.

If you find any caller of `_generate_plan_for_task` that the implementer missed, the deletion is a regression and must be reverted.

### 4.6 Is the AGENTS.md §12 refinement coherent with the rest of the document?

1. Read the full §12 section after the edit, not just the diff. Check that the new "Zero callers is NOT evidence of deprecation" rule does not contradict any earlier rule about "minimal diffs" or "don't add speculative code".
2. Check that the Legacy hunting protocol steps 1-5 form a complete decision tree: every path must end in either `delete + report replacement`, `reconnect`, or `annotate with DEPRECATED marker`. No code path should be ambiguous.

### 4.7 Is `gimo_chat` left-as-is really justified, or is the implementer hiding a violation behind "MCP stdio timeout"?

1. Read the current `gimo_chat` body. Verify that it:
   - Creates a new thread via `POST /ops/threads` if `thread_id` is empty.
   - Delegates the actual chat via `POST /ops/threads/{id}/chat` through a background `asyncio.ensure_future()` task.
   - Records failures as turns with `agent_id='gimo_chat_error'`.
   - Returns a polling instruction, not the response itself.
2. Verify the MCP timeout claim: the implementer originally stated "~60s" but the peer reviewer found `ClientSession` has no fixed read timeout by default (`session.py#L116`), and the defaults are 30s general / 300s SSE (`_httpx_utils.py#L10`). The justification is: the agentic loop can take 5–20 minutes, which exceeds any of these values. Verify this by checking if `POST /ops/threads/{id}/chat` blocks for the full duration of the agentic loop (it does: `await AgenticLoopService.run(...)` in `conversation_router.py:199`). If the endpoint blocks for minutes, the fire-and-return pattern is correct regardless of the exact client timeout.
3. Verify the alternative path: does `tools/gimo_server/routers/ops/conversation_router.py` have ANY async dispatch endpoint? If yes, `gimo_chat` should use it and not manage its own background task. If no, the current glue is the only correct option until a backend endpoint is added.

---

## 5. The delete → restore cycle (context for the reviewer)

This is disclosed so the reviewer can evaluate the implementer's judgment honestly, not to spin it:

**Initial cut (before user intervention)**: the implementer deleted `gimo_start_engine`, `gimo_get_server_info`, `gimo_reload_worker`, and `_generate_plan_for_task`, arguing F-02/F-09 + "zero callers" + "MCP should be thin proxies".

**User first intervention**: asked "why did you delete `gimo_start_engine`?" The implementer explained the reasoning, then the user pointed out the MCP-only operator scenario (Claude Desktop stdio bridge has filesystem access, backend may not be running, the bridge is the only path). The implementer acknowledged the error and restored `gimo_start_engine` as a thin trampoline over the canonical launcher (not as the original self-forking implementation).

**User second intervention**: asked the implementer to validate its operating definition of "dead code". The implementer had been using *"zero callers = deletable"*, which the user corrected to *"dead code means code functionally replaced by a canonical alternative; zero callers without a canonical replacement means reconnect, not delete"*. The implementer acknowledged the correction and applied it to the remaining two deletions:
- `gimo_get_server_info`: no canonical replacement (backend can't introspect its own import cache from outside its process) → **restored as-is**.
- `gimo_reload_worker`: no canonical replacement with equivalent semantics (bounce ≠ hot-reload) → **restored gated by `GIMO_DEV_MODE`** to mitigate the technical risks (`importlib.reload` fragility) while respecting the reconnect rule.
- `_generate_plan_for_task`: canonical replacement at `/ops/generate-plan` confirmed, plus it was a private function never exposed as an MCP tool → **deletion stands**.

**User third intervention**: requested an `AGENTS.md §12` refinement to encode the corrected definition, to prevent this same over-deletion pattern from recurring.

**Implication for the reviewer**: the implementer demonstrated susceptibility to "aggressive deletion" bias and required two user corrections to land the right policy. **If you find any sign that the remaining `gimo_chat` as-is decision is the same bias repeating ("I deleted everything else, so let me leave this alone to feel balanced")**, flag it. The implementer's own defense for leaving `gimo_chat` alone is the MCP stdio timeout, which should be independently verified.

---

## 6. Known residual risks the implementer surfaces

1. **`gimo_chat` `_BACKGROUND_CHAT_TASKS` pattern remains**. Justified as MCP stdio glue, but it IS a deviation from "thin proxy" ideal. Follow-up: add `POST /ops/threads/{id}/chat/dispatch` to the backend that queues the agentic loop and returns 202 with `thread_id`, then `gimo_chat` becomes a true thin proxy. This requires backend work and is explicitly out of scope for this commit.

2. **`gimo_reload_worker` risks**. Even behind the `GIMO_DEV_MODE` gate, `importlib.reload` is known to be fragile. The tool's docstring enumerates the risks but does not enforce them — a developer invoking it carelessly could still cause state corruption. Acceptable trade-off for dev velocity, but it is a trade-off.

3. **Preexisting `respx`-dependent test failures** (`test_adapters.py`, `test_openai_compat_adapter.py`) were not addressed in this commit. They were broken on `main` before. Not a regression, but a standing gap. Follow-up: add `respx` to `pyproject.toml` or replace the tests.

4. **Preexisting conformance ↔ unit cross-pollution** when both suites run in a single pytest invocation is documented in `memory/MEMORY.md`. Not a regression.

5. **The new `gimo_start_engine` delegates to `gimo_cli.commands.server.start_server()`** (the canonical lifecycle authority, rewritten by GPT-5.4). If GPT-5.4's launcher cleanup has any bug that the implementer did not catch, it will now be invoked via MCP — expanding the blast radius of any launcher bug. The implementer validated the launcher via `gimo up` directly in this session and it worked, but a more thorough test of the chain (MCP → canonical launcher) would require running an actual MCP stdio client against a bridge process, which was not done. (**Post-review correction**: the original text incorrectly named `scripts/dev/launcher.py` as the canonical path; the correct canonical is `gimo_cli.commands.server.start_server` in `server.py`.)

---

## 7. What the implementer did NOT do

To help the reviewer scope the review:

- Did NOT touch any other file in `tools/gimo_server/mcp_bridge/`.
- Did NOT touch `gimo_cli/commands/server.py` (owned by GPT-5.4's recent work; the canonical lifecycle authority that `gimo_start_engine` and `gimo_stop_engine` trampoline into).
- Did NOT add any new tests. The claim is that existing conformance tests + the gate sanity check via in-process instantiation are sufficient proof. If the reviewer believes a new test (e.g., `test_mcp_native_tools_are_thin_proxies.py`) should be added, flag it.
- Did NOT address F-01 launcher proliferation findings (6 other launcher paths still exist in the repo). Out of scope for this specific commit.
- Did NOT address F-03 run-status taxonomy codegen. Out of scope.
- Did NOT address F-06 license Pydantic consolidation. Out of scope.
- Did NOT run the full test suite (`python -m pytest -x -q`). Only the affected tests and conformance tests.
- Did NOT push to remote. The commit is local on `main` only.

---

## 8. Reviewer verdict template

When you're done, please respond with:

```
## Peer review verdict for commit 291f48a

### Verification
- [ ] AST parse clean: YES / NO (details)
- [ ] Tool count gate behavior: YES / NO (22 off, 23 on)
- [ ] `gimo_get_status` key parity with HTTP: YES / NO
- [ ] `gimo_start_engine` delegates to canonical launcher only: YES / NO
- [ ] `gimo_stop_engine` uses only canonical shutdown helpers: YES / NO
- [ ] `_generate_plan_for_task` deletion has canonical replacement: YES / NO
- [ ] AGENTS.md §12 internally consistent: YES / NO
- [ ] `gimo_chat` as-is justification holds (blocking endpoint + finite client timeouts makes fire-and-return the correct pattern): YES / NO

### Issues found (if any)
- ...

### Regressions introduced
- ...

### Verdict
GREEN / YELLOW / RED

### If YELLOW or RED
- Specific remediation required: ...
```

Return to implementer. If RED, implementer reverts the commit and iterates. If YELLOW, implementer addresses named issues and re-submits. If GREEN, the cleanup is accepted and the next finding in the R21 backlog can be attacked.

---

## 9. Bottom line for the reviewer

This commit is trying to kill a specific pattern: **MCP native tools inventing backend state or duplicating backend capability**. It succeeds partially (gimo_get_status is honest now, start/stop engine delegate to canonical, dead code deleted) and deliberately leaves one exception (gimo_chat) with a documented justification. The AGENTS.md refinement is the more durable contribution — it encodes a rule that the implementer learned the hard way in this same session.

The implementer is asking you to disagree actively, not to rubber-stamp. Find the blind spot.
