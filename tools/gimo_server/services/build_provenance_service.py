"""R18 Change 10 — auditable build provenance + runtime freshness signal.

Solves the R18 meta-finding: pytest could pass while the running server
served stale bytecode because there was no in-process way to compare what
was loaded to what's on disk. This service exposes two orthogonal facts:

1. **Provenance** (load-bearing, computed once at import):
   - ``git_sha``: read from ``GIMO_BUILD_SHA`` env (set by launcher to
     ``git rev-parse HEAD``); falls back to calling ``git`` if unset.
   - ``build_epoch``: wall-clock time this process imported the service.
   - ``process_started_at``: ISO-8601 form of the same.
   - ``python_version`` / ``pyc_invalidation_mode``.

2. **Module freshness** (operational signal, computed live):
   Walks ``sys.modules`` for modules under ``tools/gimo_server/`` and
   compares the loaded module's ``__file__`` mtime against the source
   file on disk. Reports ``worst_case_drift_seconds`` and the top drifted
   modules. **Caveat**: this catches the common case (file edited after
   import) but is not a proof of freshness — a file saved within the same
   second as import (bpo-31772) or a ``.pyc`` from an unrelated source
   won't be caught. The real guarantee is ``checked-hash`` bytecode
   invalidation plus the launcher-injected ``GIMO_BUILD_SHA``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_IMPORT_EPOCH: float = time.time()
_IMPORT_ISO: str = datetime.now(timezone.utc).isoformat()


def _resolve_git_sha() -> str:
    env_sha = os.environ.get("GIMO_BUILD_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


_GIT_SHA: str = _resolve_git_sha()


def _module_freshness() -> dict[str, Any]:
    Path(__file__).resolve().parents[2]  # tools/gimo_server
    worst_drift: float = 0.0
    drifted: list[dict[str, Any]] = []
    checked = 0

    for mod_name, module in list(sys.modules.items()):
        if not mod_name.startswith("tools.gimo_server"):
            continue
        mod_file = getattr(module, "__file__", None)
        if not mod_file:
            continue
        try:
            src = Path(mod_file)
            if src.suffix == ".pyc":
                # Find the .py source via __cached__ inverse — best effort
                continue
            if not src.exists():
                continue
            disk_mtime = src.stat().st_mtime
            # Loaded bytecode timestamp is best approximated via the
            # module object's source mtime at import time; sys.modules
            # doesn't preserve it, so we use _IMPORT_EPOCH as a floor.
            drift = disk_mtime - _IMPORT_EPOCH
            checked += 1
            if drift > worst_drift:
                worst_drift = drift
            if drift > 1.0:
                drifted.append({
                    "module": mod_name,
                    "drift_seconds": round(drift, 3),
                })
        except Exception:
            continue

    drifted.sort(key=lambda d: d["drift_seconds"], reverse=True)
    return {
        "modules_checked": checked,
        "worst_case_drift_seconds": round(worst_drift, 3),
        "top_drifted": drifted[:5],
        "caveat": (
            "Detects files edited after process import. Does NOT catch "
            "same-second edits (bpo-31772) or .pyc from an unrelated "
            "source tree. Use checked-hash invalidation + GIMO_BUILD_SHA "
            "for strict guarantees."
        ),
    }


def get_build_info() -> dict[str, Any]:
    """Return the full /ops/health/info payload."""
    return {
        "git_sha": _GIT_SHA,
        "build_epoch": _IMPORT_EPOCH,
        "process_started_at": _IMPORT_ISO,
        "python_version": sys.version.split()[0],
        "pyc_invalidation_mode": getattr(sys.flags, "check_hash_based_pycs", "default") or "default",
        "module_freshness": _module_freshness(),
    }
