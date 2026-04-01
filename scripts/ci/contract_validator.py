"""Contract validator: cross-checks backend routes, OpenAPI spec, and frontend calls.

Usage:
    python scripts/ci/contract_validator.py

Reports:
    1. Endpoints in OpenAPI but NOT in backend (phantom routes)
    2. Endpoints in backend but NOT in OpenAPI (undocumented)
    3. Endpoints frontend calls but NOT in backend (broken calls)
    4. Summary statistics
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tools" / "gimo_server"
FRONTEND = ROOT / "tools" / "orchestrator_ui" / "src"
OPENAPI = SERVER / "openapi.yaml"


# ── 1. Extract backend routes via FastAPI introspection ─────────────

def get_backend_routes() -> set[str]:
    """Return set of 'METHOD /path' strings from the live FastAPI app."""
    sys.path.insert(0, str(ROOT))
    from tools.gimo_server.main import app  # noqa: E402

    routes = set()
    skip = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    for r in app.routes:
        if hasattr(r, "path") and hasattr(r, "methods"):
            if r.path in skip:
                continue
            for m in r.methods:
                if m in ("HEAD", "OPTIONS"):
                    continue
                routes.add(f"{m} {r.path}")
    return routes


# ── 2. Parse OpenAPI spec paths ────────────────────────────────────

def get_openapi_routes() -> set[str]:
    """Parse openapi.yaml and return set of 'METHOD /path' strings."""
    if not OPENAPI.exists():
        return set()

    routes = set()
    text = OPENAPI.read_text(encoding="utf-8")

    # Simple YAML path parser — matches top-level path keys under 'paths:'
    in_paths = False
    current_path = None
    for line in text.splitlines():
        stripped = line.strip()
        # Detect 'paths:' section
        if line.startswith("paths:"):
            in_paths = True
            continue
        if in_paths:
            # New top-level section ends paths
            if not line.startswith(" ") and not line.startswith("\t") and stripped and not stripped.startswith("#"):
                in_paths = False
                continue
            # Path key (2-space indent)
            path_match = re.match(r"^  (/\S+):", line)
            if path_match:
                current_path = path_match.group(1)
                # Remove trailing colon artifacts
                current_path = current_path.rstrip(":")
                continue
            # Method key (4-space indent)
            if current_path:
                method_match = re.match(r"^    (get|post|put|delete|patch|head|options):", line)
                if method_match:
                    method = method_match.group(1).upper()
                    routes.add(f"{method} {current_path}")
    return routes


# ── 3. Extract frontend API calls ─────────────────────────────────

def get_frontend_calls() -> set[str]:
    """Statically extract API paths from frontend TypeScript source."""
    if not FRONTEND.exists():
        return set()

    calls = set()
    # Patterns: `${API_BASE}/some/path`, `${API_BASE}/some/path?...`
    pattern = re.compile(r'API_BASE\}`?\s*/([^`"\'?\s]+)')
    method_pattern = re.compile(r"method:\s*['\"](\w+)['\"]")

    for ts_file in FRONTEND.rglob("*.ts"):
        _extract_calls(ts_file, pattern, method_pattern, calls)
    for tsx_file in FRONTEND.rglob("*.tsx"):
        _extract_calls(tsx_file, pattern, method_pattern, calls)

    return calls


def _extract_calls(filepath: Path, pattern, method_pattern, calls: set):
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    for i, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        raw_path = "/" + match.group(1).rstrip(",);")
        # Normalize JS template expressions:
        # ${encodeURIComponent(foo)} -> {param}
        # ${foo.bar} -> {param}
        # ${foo} -> {param}
        raw_path = re.sub(r"\$\{[^}]+\}", "{param}", raw_path)
        # Normalize {someId} -> {param}
        raw_path = re.sub(r"\{[^}]+\}", "{param}", raw_path)
        # Remove query strings appended via template: ?foo
        raw_path = re.sub(r"\?.*$", "", raw_path)
        # Remove {param} stuck to end without / separator (query param artifacts)
        raw_path = re.sub(r"([a-z])\{param\}$", r"\1", raw_path)
        # Remove trailing slashes
        raw_path = raw_path.rstrip("/") or "/"
        # Skip paths that still have unresolved JS expressions
        if "$" in raw_path or "(" in raw_path:
            continue
        # Skip WebSocket paths
        if raw_path == "/ws":
            continue

        # Detect HTTP method from surrounding context (same line or next few lines)
        context = "\n".join(lines[max(0, i - 2) : i + 5])
        method_match = method_pattern.search(context)
        if method_match:
            method = method_match.group(1).upper()
        else:
            method = "GET"  # default for fetch

        calls.add(f"{method} {raw_path}")


# ── 4. Normalize paths for comparison ─────────────────────────────

def normalize_path(route: str) -> str:
    """Normalize path parameters for comparison.

    Converts specific param names like {draft_id} or {draftId} to {param}
    so backend {draft_id} matches frontend {draftId}.
    """
    method, path = route.split(" ", 1)
    # Replace all {something} with {param}
    normalized = re.sub(r"\{[^}]+\}", "{param}", path)
    return f"{method} {normalized}"


def normalize_set(routes: set[str]) -> dict[str, set[str]]:
    """Return dict mapping normalized route -> set of original routes."""
    result: dict[str, set[str]] = {}
    for r in routes:
        key = normalize_path(r)
        result.setdefault(key, set()).add(r)
    return result


# ── 5. Report ──────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("GIMO Contract Validator")
    print("=" * 70)

    backend = get_backend_routes()
    openapi = get_openapi_routes()
    frontend = get_frontend_calls()

    backend_norm = normalize_set(backend)
    openapi_norm = normalize_set(openapi)
    frontend_norm = normalize_set(frontend)

    backend_keys = set(backend_norm.keys())
    openapi_keys = set(openapi_norm.keys())
    frontend_keys = set(frontend_norm.keys())

    # 1. Phantom routes: in OpenAPI but not in backend
    phantom = openapi_keys - backend_keys
    print(f"\n[1] PHANTOM ROUTES (in OpenAPI, not in backend): {len(phantom)}")
    for p in sorted(phantom):
        for orig in sorted(openapi_norm[p]):
            print(f"    {orig}")

    # 2. Undocumented: in backend but not in OpenAPI
    undocumented = backend_keys - openapi_keys
    # Filter out well-known internal routes
    internal_prefixes = ("/health", "/ws", "/", "/auth/", "/me", "/ui/", "/tree", "/file", "/search", "/diff")
    undocumented_filtered = set()
    for u in undocumented:
        method, path = u.split(" ", 1)
        if any(path == prefix or path.startswith(prefix) for prefix in internal_prefixes):
            continue
        undocumented_filtered.add(u)

    print(f"\n[2] UNDOCUMENTED (in backend, not in OpenAPI): {len(undocumented_filtered)}")
    for u in sorted(undocumented_filtered):
        for orig in sorted(backend_norm[u]):
            print(f"    {orig}")

    # 3. Broken calls: frontend calls endpoint not in backend
    broken = frontend_keys - backend_keys
    print(f"\n[3] BROKEN FRONTEND CALLS (frontend calls, not in backend): {len(broken)}")
    for b in sorted(broken):
        for orig in sorted(frontend_norm[b]):
            print(f"    {orig}")

    # 4. Frontend coverage: how many frontend calls match backend
    covered = frontend_keys & backend_keys
    print(f"\n[4] FRONTEND COVERAGE: {len(covered)}/{len(frontend_keys)} calls match backend routes")

    # 5. OpenAPI coverage
    openapi_covered = openapi_keys & backend_keys
    print(f"[5] OPENAPI COVERAGE: {len(openapi_covered)}/{len(backend_keys)} backend routes documented")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"Backend routes:     {len(backend)}")
    print(f"OpenAPI paths:      {len(openapi)}")
    print(f"Frontend calls:     {len(frontend)}")
    print(f"Phantom routes:     {len(phantom)}")
    print(f"Undocumented (/ops): {len(undocumented_filtered)}")
    print(f"Broken FE calls:    {len(broken)}")
    print(f"{'=' * 70}")

    # Exit code: 1 if broken frontend calls exist
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
