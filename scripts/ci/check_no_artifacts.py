"""Fail fast if generated artifacts are about to be committed.

Supports two modes:
  - --staged: inspect staged files (pre-commit)
  - --tracked: inspect currently tracked files (CI / quality gates)

This script is intentionally conservative: if you *really* want to commit an
artifact, put it under a dedicated allowed area (e.g. docs/evidence/) and/or
update the allowlist below.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess


FORBIDDEN_GLOBS: list[str] = [
    ".orch_data/**",
    ".orch_snapshots/**",
    "logs/**",
    "tmp/**",
    "out/**",
    "artifacts/**",
    "tools/orchestrator_ui/coverage/**",
    "tools/orchestrator_ui/dist/**",
    "tools/orchestrator_ui/.env.local",
    "tools/orchestrator_ui/vitest-results.json",
    "tests/metrics/*.json",
    "tests/metrics/*.md",
    "test_diag*.txt",
    "test_results*.txt",
    "test_failures*.txt",
    "{console.error*",
    ".claude/settings.local.json",
]

# Explicit allowlist exceptions (evaluated after FORBIDDEN_GLOBS)
ALLOWED_GLOBS: list[str] = [
    "tests/metrics/golden/**",
    "docs/evidence/**",
    "docs/history/**",
]


def _git_lines(args: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        raise SystemExit(proc.returncode)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _matches_any(path: str, globs: list[str]) -> bool:
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _is_forbidden(path: str) -> bool:
    if _matches_any(path, ALLOWED_GLOBS):
        return False
    return _matches_any(path, FORBIDDEN_GLOBS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="Check staged changes")
    parser.add_argument("--tracked", action="store_true", help="Check tracked files")
    args = parser.parse_args()

    if not args.staged and not args.tracked:
        parser.error("Expected --staged and/or --tracked")

    offending: list[str] = []

    if args.tracked:
        for f in _git_lines(["ls-files"]):
            if _is_forbidden(f):
                offending.append(f)

    if args.staged:
        # Ignore deletions: it's always ok to *remove* generated artifacts.
        for f in _git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]):
            if _is_forbidden(f):
                offending.append(f)

    if offending:
        offending = sorted(set(offending))
        print("\n[BLOCKED] Generated artifacts detected:\n")
        for f in offending:
            print(f"  - {f}")
        print(
            "\nMove artifacts under docs/evidence/ (if you really need them), "
            "or regenerate them locally.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
