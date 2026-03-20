from __future__ import annotations

import re
from pathlib import Path

from tools.gimo_server.main import app


UI_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "tools" / "orchestrator_ui" / "src"
FETCH_PATTERN = re.compile(r"fetch\(\s*`\$\{API_BASE\}([^`]+)`")
IGNORED_DYNAMIC_PATHS = {
    "/ui/service/{param}",
}


def _normalize_frontend_path(raw: str) -> str:
    path = raw.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{param}", path)
    if path.endswith("{param}") and not path.endswith("/{param}"):
        path = path[: -len("{param}")]
    path = path.replace("{param}{param}", "{param}")
    return path.rstrip("/") or "/"


def _frontend_paths() -> set[str]:
    out: set[str] = set()
    for file_path in UI_SOURCE_ROOT.rglob("*.[tj]s*"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for match in FETCH_PATTERN.finditer(text):
            normalized = _normalize_frontend_path(match.group(1))
            if normalized == "{param}":
                continue
            out.add(normalized)
    return out


def _backend_paths() -> set[str]:
    out: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        normalized = re.sub(r"\{[^}]+\}", "{param}", path).rstrip("/") or "/"
        out.add(normalized)
    return out


def test_phase1_frontend_api_paths_exist_in_backend():
    frontend_paths = _frontend_paths()
    backend_paths = _backend_paths()

    missing = sorted(
        path for path in frontend_paths
        if path not in backend_paths and path not in IGNORED_DYNAMIC_PATHS
    )

    assert missing == []
