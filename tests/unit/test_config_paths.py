from __future__ import annotations

from pathlib import Path

from tools.gimo_server import config


def test_load_settings_defaults_repo_root_to_base_dir(tmp_path: Path, monkeypatch) -> None:
    repo_root = (tmp_path / "repo_root").resolve()
    monkeypatch.delenv("ORCH_REPO_ROOT", raising=False)
    monkeypatch.setattr(config, "_get_base_dir", lambda: repo_root)
    monkeypatch.setattr(config, "_migrate_to_unified_credentials", lambda: None)

    settings = config._build_settings()

    assert settings.repo_root_dir == repo_root
    assert settings.ops_data_dir == repo_root / ".orch_data" / "ops"
    assert settings.gics_token_path == repo_root / ".orch_data" / "ops" / "gics.token"
