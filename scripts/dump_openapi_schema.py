"""Dump the live OpenAPI schema derived from the FastAPI app.

This is the canonical source of truth for frontend-consumable contracts.
The output file is consumed by `openapi-typescript` to generate
`tools/orchestrator_ui/src/types/backend-generated.ts`.

Run via:
    python scripts/dump_openapi_schema.py

The schema is derived from Pydantic models (single source of truth),
not from the hand-maintained `tools/gimo_server/openapi.yaml` which may drift.

CI gate: run this script + npm codegen + diff. If files changed, the
frontend contract is out of sync with the backend — fail the build.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "tools" / "orchestrator_ui" / "src" / "types" / "backend-schema.json"


def main() -> int:
    # Import lazily so this script doesn't trigger FastAPI startup side effects on import.
    sys.path.insert(0, str(REPO_ROOT))
    from tools.gimo_server.main import app

    schema = app.openapi()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Stable, sorted output so diffs are deterministic.
    OUTPUT.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
