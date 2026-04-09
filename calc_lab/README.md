# calc_lab — vehicle workspace for live calculator e2e runs

This directory is the **active** workspace where GIMO's agentic loop builds and
exercises calculator code as a real side-effect during end-to-end vehicle runs
(R19+).

## Purpose

- This is **not** a museum. Files here are produced by live agent runs and may
  be regenerated, modified, or deleted between rounds.
- The historical sandbox `../gimo_prueba/` is now archive-only. Its forensic
  artifacts (audit logs, RCA, side-effect text drops from R9..R19) live under
  `../gimo_prueba/evidence/` and must not be edited.

## Layout

```
calc_lab/
  README.md         <- this file (do not delete)
  (everything else) <- agent-produced; safe to wipe between runs
```

## How it is used

When a vehicle e2e is run, the operator points the chat thread at this
workspace:

```
python gimo.py chat --workspace-root calc_lab -m "Build a calculator..."
```

The agentic loop's tool executor (read/write/shell/...) operates inside this
directory. Every tool invocation produces governed evidence in the GIMO
backend (proof chain, trust events, traces, cost). Verifying that evidence is
the actual e2e — the files here are only the visible side effect.

## Why split from `gimo_prueba/`

`gimo_prueba/` accumulated cross-round forensic artifacts (R9..R19) and a
nested `.git/` of its own. Reusing it as a live workspace contaminates
forensic state. This directory is a clean room: empty start, side effects
visible, easy to wipe.
