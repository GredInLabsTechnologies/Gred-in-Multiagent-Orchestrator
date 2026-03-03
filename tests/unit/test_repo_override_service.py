from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tools.gimo_server.services.repo_override_service import RepoOverrideService


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_set_and_get_override_persists_and_returns_etag(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)

    data = RepoOverrideService.set_human_override(
        repo_id=str(tmp_path / "repoA"),
        set_by_user="operator-token",
        source="ui",
        reason="manual",
    )

    assert override_path.exists()
    assert data.get("etag")
    loaded = RepoOverrideService.get_active_override()
    assert loaded is not None
    assert loaded["repo_id"] == str(tmp_path / "repoA")
    assert loaded["etag"] == data["etag"]


def test_update_override_requires_matching_etag(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)

    first = RepoOverrideService.set_human_override(
        repo_id=str(tmp_path / "repoA"),
        set_by_user="operator-token",
    )

    try:
        RepoOverrideService.set_human_override(
            repo_id=str(tmp_path / "repoB"),
            set_by_user="operator-token",
            if_match_etag='"bad"',
        )
        assert False, "Expected OVERRIDE_ETAG_MISMATCH"
    except ValueError as exc:
        assert str(exc) == "OVERRIDE_ETAG_MISMATCH"

    updated = RepoOverrideService.set_human_override(
        repo_id=str(tmp_path / "repoB"),
        set_by_user="operator-token",
        if_match_etag=first["etag"],
    )
    assert updated["repo_id"] == str(tmp_path / "repoB")
    assert updated["etag"] != first["etag"]


def test_expired_override_is_cleaned_up(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)

    now = datetime.now(timezone.utc)
    expired_payload = {
        "repo_id": str(tmp_path / "repoA"),
        "set_by_user": "operator",
        "set_at": _z(now - timedelta(hours=2)),
        "expires_at": _z(now - timedelta(hours=1)),
        "reason": "manual",
        "source": "ui",
        "version": 1,
        "etag": '"expired"',
    }
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(json.dumps(expired_payload), encoding="utf-8")

    active = RepoOverrideService.get_active_override()
    assert active is None
    assert not override_path.exists()


def test_revoke_requires_matching_etag(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)

    current = RepoOverrideService.set_human_override(
        repo_id=str(tmp_path / "repoA"),
        set_by_user="operator-token",
    )

    try:
        RepoOverrideService.revoke_human_override(actor="operator-token", if_match_etag='"bad"')
        assert False, "Expected OVERRIDE_ETAG_MISMATCH"
    except ValueError as exc:
        assert str(exc) == "OVERRIDE_ETAG_MISMATCH"

    assert RepoOverrideService.revoke_human_override(
        actor="operator-token",
        if_match_etag=current["etag"],
    ) is True
    assert not override_path.exists()
