"""R18 Change 10 — build provenance service tests."""
from __future__ import annotations

import os


def test_get_build_info_shape():
    from tools.gimo_server.services.build_provenance_service import get_build_info

    info = get_build_info()
    assert set(info.keys()) >= {
        "git_sha",
        "build_epoch",
        "process_started_at",
        "python_version",
        "pyc_invalidation_mode",
        "module_freshness",
    }
    assert isinstance(info["git_sha"], str) and info["git_sha"]
    assert isinstance(info["build_epoch"], float)
    assert "T" in info["process_started_at"]

    freshness = info["module_freshness"]
    assert "modules_checked" in freshness
    assert "worst_case_drift_seconds" in freshness
    assert "top_drifted" in freshness
    assert "caveat" in freshness


def test_git_sha_env_override(monkeypatch):
    monkeypatch.setenv("GIMO_BUILD_SHA", "deadbeef1234")
    # Re-resolve by reimporting the helper function directly
    from tools.gimo_server.services.build_provenance_service import _resolve_git_sha
    assert _resolve_git_sha() == "deadbeef1234"
