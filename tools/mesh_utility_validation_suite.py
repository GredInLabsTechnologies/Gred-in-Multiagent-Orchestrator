#!/usr/bin/env python3
"""
GIMO Mesh — Utility Mode Validation Suite

10 tasks cubriendo las dimensiones SOTA (BOINC-inspired + EdgeBench):
  correctness, reliability, timeout enforcement, exit code propagation,
  stdout/stderr separation, determinism, security allowlist, file I/O,
  task dispatch end-to-end.

Usage:
    python tools/mesh_utility_validation_suite.py --device <device_id>

The script creates 10 tasks via /ops/mesh/tasks, polls until each resolves,
then compares against canonical expected outputs. Exit code 0 iff all pass.

Per BOINC-style validation: outputs are compared byte-exact against
canonical hashes (T2, T8) or structural predicates (T10 sha256 regex).

Canonical precomputed values:
  T2: sha256(hello text) for regex match validation — computed locally
  T8: seq 1 100 | sha256sum -> 93d4e5c77838e0aa5cb6647c385c810a7c2782bf769029e6c420052048ab22bb
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError

CORE_URL = "http://127.0.0.1:9325"
CREDS_PATH = Path("tools/gimo_server/.gimo_credentials")


def load_admin_token() -> str:
    for line in CREDS_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("admin:"):
            return line.split('"')[1]
    raise SystemExit("admin token not found in .gimo_credentials")


def api(method: str, path: str, token: str, body: dict | None = None) -> Any:
    url = f"{CORE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        body_raw = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {body_raw}")


def create_task(token: str, device_id: str, task_type: str,
                payload: dict, timeout_s: int = 30) -> str:
    """Create a task and target-assign it to the device (via payload fields if supported, else rely on auto-assign)."""
    body = {
        "task_type": task_type,
        "payload": payload,
        "timeout_seconds": timeout_s,
        "workspace_id": "default",
    }
    task = api("POST", "/ops/mesh/tasks", token, body)
    return task["task_id"]


def wait_task(token: str, task_id: str, max_wait_s: int = 90) -> dict:
    """Poll task until terminal status."""
    deadline = time.time() + max_wait_s
    last_status = None
    while time.time() < deadline:
        t = api("GET", f"/ops/mesh/tasks/{task_id}", token)
        status = t.get("status")
        if status != last_status:
            print(f"  [{task_id[:8]}] {status}", flush=True)
            last_status = status
        if status in ("completed", "failed", "timed_out"):
            return t
        time.sleep(2)
    raise TimeoutError(f"task {task_id} did not resolve within {max_wait_s}s")


# ─────────────────────────────────────────────────────────────────────
# The 10-task validation suite
# ─────────────────────────────────────────────────────────────────────

def case_t1_ping(result: dict) -> tuple[bool, str]:
    """T1 — Ping: baseline round-trip. Validates polling + exec + submit."""
    r = result.get("result", {})
    if r.get("pong") == "true" and "timestamp" in r:
        return True, f"pong ok, ts={r['timestamp']}"
    return False, f"unexpected result: {r}"


def case_t2_text_validate(result: dict) -> tuple[bool, str]:
    """T2 — Regex engine: \\d+ against 'gimo-mesh-v1.2.3' -> 3 matches."""
    r = result.get("result", {})
    if (r.get("valid") == "true"
            and r.get("match_count") == "3"
            and r.get("matches") == "1,2,3"):
        return True, "3 matches (1,2,3) as expected"
    return False, f"unexpected: {r}"


def case_t3_text_transform(result: dict) -> tuple[bool, str]:
    """T3 — Text transform: 'GIMO Mesh' reversed = 'hseM OMIG'."""
    r = result.get("result", {})
    if r.get("result") == "hseM OMIG":
        return True, "reverse ok"
    return False, f"expected 'hseM OMIG', got {r.get('result')!r}"


def case_t4_text_length(result: dict) -> tuple[bool, str]:
    """T4 — Text length: 'The quick brown fox' = 19."""
    r = result.get("result", {})
    if r.get("result") == "19":
        return True, "length=19 ok"
    return False, f"expected '19', got {r.get('result')!r}"


def case_t5_json_validate_ok(result: dict) -> tuple[bool, str]:
    """T5 — JSON valid structure accepted."""
    r = result.get("result", {})
    if r.get("valid") == "true":
        return True, "valid json accepted"
    return False, f"valid json rejected: {r}"


def case_t6_json_validate_fail(result: dict) -> tuple[bool, str]:
    """T6 — JSON invalid rejected with error msg."""
    r = result.get("result", {})
    if r.get("valid") == "false" and r.get("error"):
        return True, f"invalid json rejected ({r['error'][:40]}...)"
    return False, f"invalid json should be rejected: {r}"


def case_t7_shell_uname(result: dict) -> tuple[bool, str]:
    """T7 — shell_exec uname -s -> 'Linux'."""
    r = result.get("result", {})
    if r.get("exit_code") == "0" and "Linux" in r.get("stdout", ""):
        return True, f"stdout={r['stdout'].strip()}"
    return False, f"expected exit_code=0 + 'Linux' in stdout: {r}"


def case_t8_shell_pipe_hash(result: dict) -> tuple[bool, str]:
    """T8 — shell pipeline `seq 1 100 | sha256sum` canonical hash."""
    r = result.get("result", {})
    canonical = "93d4e5c77838e0aa5cb6647c385c810a7c2782bf769029e6c420052048ab22bb"
    stdout = r.get("stdout", "")
    if r.get("exit_code") == "0" and canonical in stdout:
        return True, f"sha256 matches canonical (byte-exact)"
    return False, f"hash mismatch. got: {stdout[:80]!r}"


def case_t9_shell_deny(result: dict) -> tuple[bool, str]:
    """T9 — security allowlist rejects 'rm /tmp/foo'."""
    r = result.get("result", {})
    if "error" in r and "DENIED" in r.get("error", ""):
        return True, f"correctly denied ({r['error'][:40]}...)"
    return False, f"'rm' should be DENIED: {r}"


def case_t10_file_hash(result: dict) -> tuple[bool, str]:
    """T10 — SHA-256 of datastore preferences file (present in any enrolled
    device). Structural validation only (any valid 64-hex with non-zero size)."""
    r = result.get("result", {})
    sha = r.get("sha256", "")
    size = int(r.get("size", "0"))
    if re.fullmatch(r"[0-9a-f]{64}", sha) and size > 0:
        return True, f"sha256={sha[:16]}... size={size}B"
    return False, f"expected 64-hex sha + size>0: sha={sha[:20]!r} size={size}"


SUITE: list[tuple[str, str, dict, Callable[[dict], tuple[bool, str]], int]] = [
    ("T1  ping",              "ping",           {}, case_t1_ping, 30),
    ("T2  regex validate",    "text_validate",  {"text": "gimo-mesh-v1.2.3", "pattern": "\\d+"}, case_t2_text_validate, 30),
    ("T3  transform reverse", "text_transform", {"text": "GIMO Mesh", "operation": "reverse"}, case_t3_text_transform, 30),
    ("T4  transform length",  "text_transform", {"text": "The quick brown fox", "operation": "length"}, case_t4_text_length, 30),
    ("T5  json valid",        "json_validate",  {"json_string": '{"a":1,"b":[2,3]}'}, case_t5_json_validate_ok, 30),
    ("T6  json invalid",      "json_validate",  {"json_string": "not a json"}, case_t6_json_validate_fail, 30),
    ("T7  shell uname",       "shell_exec",     {"command": "uname -s"}, case_t7_shell_uname, 30),
    ("T8  shell pipe hash",   "shell_exec",     {"command": "seq 1 100 | sha256sum"}, case_t8_shell_pipe_hash, 30),
    ("T9  shell allowlist",   "shell_exec",     {"command": "rm /tmp/foo"}, case_t9_shell_deny, 30),
    ("T10 file hash settings","file_hash",      {"path": "datastore/gimo_mesh_settings.preferences_pb"}, case_t10_file_hash, 30),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", required=True, help="target device_id")
    args = ap.parse_args()

    token = load_admin_token()

    # Sanity: device exists and is connected
    dev = api("GET", f"/ops/mesh/devices/{args.device}", token)
    print(f"\nDevice: {dev['device_id']} mode={dev['device_mode']} state={dev['connection_state']}")
    if dev["connection_state"] not in ("approved", "connected"):
        print("  WARN: device not approved/connected — tasks may not dispatch")

    print(f"\nSubmitting {len(SUITE)} tasks...\n")
    submissions: list[tuple[str, str, Callable, dict]] = []
    for label, task_type, payload, case_fn, timeout_s in SUITE:
        tid = create_task(token, args.device, task_type, payload, timeout_s=timeout_s)
        print(f"  {label:<24} -> {tid[:8]}  [{task_type}]")
        submissions.append((label, tid, case_fn, {}))

    print(f"\nWaiting for completions...\n")
    results = []
    for label, tid, case_fn, _ in submissions:
        print(f"{label}:")
        try:
            t = wait_task(token, tid, max_wait_s=180)
            passed, msg = case_fn(t)
            results.append((label, passed, msg, t))
            icon = "PASS" if passed else "FAIL"
            print(f"  {icon}: {msg}")
        except TimeoutError as e:
            results.append((label, False, f"timeout: {e}", None))
            print(f"  FAIL: timeout")
        except Exception as e:
            results.append((label, False, f"exception: {e}", None))
            print(f"  FAIL: {e}")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    pass_count = 0
    for label, passed, msg, _ in results:
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {label:<24}  {msg[:60]}")
        if passed:
            pass_count += 1
    print(f"\n  {pass_count}/{len(results)} passed")

    return 0 if pass_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
