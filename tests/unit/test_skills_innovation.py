"""
Innovation Features Unit Tests
Tests for: Versioning, Analytics, Marketplace, Moods, Auto-Gen
"""
import json
import shutil
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from tools.gimo_server.services.skills_service import (
    ANALYTICS_DIR,
    MARKETPLACE_DIR,
    MOOD_PROMPTS,
    SKILLS_DIR,
    DuplicateCommandError,
    SkillAutoGenRequest,
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillsService,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _test_create_req(**overrides) -> SkillCreateRequest:
    defaults = {
        "name": "Test Skill",
        "description": "A test skill",
        "command": "/test-inn",
        "nodes": [
            {"id": "orch", "type": "orchestrator", "data": {"label": "Orch"}, "position": {"x": 0, "y": 0}},
            {"id": "w1", "type": "worker", "data": {"label": "Worker"}, "position": {"x": 250, "y": 0}},
        ],
        "edges": [{"id": "e1", "source": "orch", "target": "w1"}],
    }
    defaults.update(overrides)
    return SkillCreateRequest(**defaults)


@pytest.fixture(autouse=True)
def clean_dirs(tmp_path, monkeypatch):
    """Redirect all skill directories to tmp_path for isolation."""
    skills_dir = tmp_path / "skills"
    analytics_dir = tmp_path / "analytics"
    marketplace_dir = tmp_path / "marketplace"
    lock_path = tmp_path / "skills.lock"

    skills_dir.mkdir()
    analytics_dir.mkdir()
    marketplace_dir.mkdir()

    monkeypatch.setattr("tools.gimo_server.services.skills_service.SKILLS_DIR", skills_dir)
    monkeypatch.setattr("tools.gimo_server.services.skills_service.SKILLS_LOCK", lock_path)
    monkeypatch.setattr("tools.gimo_server.services.skills_service.ANALYTICS_DIR", analytics_dir)
    monkeypatch.setattr("tools.gimo_server.services.skills_service.MARKETPLACE_DIR", marketplace_dir)

    yield

    # Cleanup
    for d in [skills_dir, analytics_dir, marketplace_dir]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


# ── Versioning Tests ─────────────────────────────────────────────────────────


class TestVersioning:
    def test_create_skill_starts_at_v1(self):
        skill = SkillsService.create_skill(_test_create_req())
        assert skill.version == 1

    def test_update_bumps_version(self):
        skill = SkillsService.create_skill(_test_create_req())
        updated = SkillsService.update_skill(skill.id, SkillUpdateRequest(name="Updated Name"))
        assert updated is not None
        assert updated.version == 2
        assert updated.name == "Updated Name"

    def test_update_archives_previous(self):
        skill = SkillsService.create_skill(_test_create_req())
        SkillsService.update_skill(skill.id, SkillUpdateRequest(description="v2 desc"))
        versions = SkillsService.list_skill_versions(skill.id)
        assert len(versions) == 1
        assert versions[0].version == 1

    def test_double_update_creates_two_versions(self):
        skill = SkillsService.create_skill(_test_create_req())
        SkillsService.update_skill(skill.id, SkillUpdateRequest(description="v2"))
        SkillsService.update_skill(skill.id, SkillUpdateRequest(description="v3"))
        versions = SkillsService.list_skill_versions(skill.id)
        assert len(versions) == 2
        current = SkillsService.get_skill(skill.id)
        assert current.version == 3

    def test_update_nonexistent_returns_none(self):
        result = SkillsService.update_skill("nonexistent-id", SkillUpdateRequest(name="X"))
        assert result is None

    def test_update_invalid_mood_raises(self):
        skill = SkillsService.create_skill(_test_create_req())
        with pytest.raises(ValueError, match="Invalid mood"):
            SkillsService.update_skill(skill.id, SkillUpdateRequest(mood="angry"))


# ── Analytics Tests ──────────────────────────────────────────────────────────


class TestAnalytics:
    def test_empty_analytics_returns_zeroes(self):
        analytics = SkillsService.get_skill_analytics("nonexistent")
        assert analytics.total_runs == 0
        assert analytics.success_rate == 0.0

    def test_record_successful_run(self):
        a = SkillsService.record_skill_run("s1", "completed", duration=1.5, tokens=100)
        assert a.total_runs == 1
        assert a.successful_runs == 1
        assert a.failed_runs == 0
        assert a.success_rate == pytest.approx(1.0)
        assert a.avg_duration_seconds == pytest.approx(1.5)
        assert a.total_tokens_used == 100

    def test_record_failed_run(self):
        a = SkillsService.record_skill_run("s2", "failed", duration=0.5)
        assert a.failed_runs == 1
        assert a.success_rate == pytest.approx(0.0)

    def test_multiple_runs_average_duration(self):
        SkillsService.record_skill_run("s3", "completed", duration=2.0)
        a = SkillsService.record_skill_run("s3", "completed", duration=4.0)
        assert a.total_runs == 2
        assert abs(a.avg_duration_seconds - 3.0) < 0.01
        assert a.success_rate == pytest.approx(1.0)

    def test_analytics_persisted(self):
        SkillsService.record_skill_run("s4", "completed", duration=1.0)
        # Read from disk
        a = SkillsService.get_skill_analytics("s4")
        assert a.total_runs == 1


# ── Marketplace Tests ────────────────────────────────────────────────────────


class TestMarketplace:
    def test_publish_skill(self):
        skill = SkillsService.create_skill(_test_create_req(command="/mp-publish"))
        published = SkillsService.publish_skill(skill.id, author="test-user")
        assert published.published is True
        assert published.author == "test-user"

    def test_list_published_skills(self):
        skill = SkillsService.create_skill(_test_create_req(command="/mp-list"))
        SkillsService.publish_skill(skill.id)
        listed = SkillsService.list_published_skills()
        assert len(listed) == 1
        assert listed[0].id == skill.id

    def test_install_from_marketplace(self):
        skill = SkillsService.create_skill(_test_create_req(command="/mp-install"))
        SkillsService.publish_skill(skill.id)
        # Delete original so we can install
        SkillsService.delete_skill(skill.id)
        installed = SkillsService.install_from_marketplace(skill.id)
        assert installed.name == skill.name
        assert "installed-from-marketplace" in installed.tags

    def test_install_duplicate_command_raises(self):
        skill = SkillsService.create_skill(_test_create_req(command="/mp-dup"))
        SkillsService.publish_skill(skill.id)
        # Try install while original still exists → should raise
        with pytest.raises(DuplicateCommandError):
            SkillsService.install_from_marketplace(skill.id)

    def test_publish_nonexistent_raises(self):
        with pytest.raises(ValueError, match="not found"):
            SkillsService.publish_skill("nonexistent")

    def test_install_nonexistent_raises(self):
        with pytest.raises(ValueError, match="not found"):
            SkillsService.install_from_marketplace("nonexistent")


# ── Moods Tests ──────────────────────────────────────────────────────────────


class TestMoods:
    def test_moods_defined(self):
        # 7 canonical + 7 legacy aliases = 14 total
        assert len(MOOD_PROMPTS) >= 7
        for canonical in ("neutral", "assertive", "calm", "analytical",
                          "exploratory", "cautious", "collaborative"):
            assert canonical in MOOD_PROMPTS

    def test_neutral_is_empty(self):
        assert MOOD_PROMPTS["neutral"] == ""

    def test_all_moods_have_prefix(self):
        for mood, prompt in MOOD_PROMPTS.items():
            if mood != "neutral":
                assert prompt.startswith("[MOOD:")

    def test_get_mood_prompt(self):
        # "forensic" is a legacy alias for "analytical"
        prompt = SkillsService.get_mood_prompt("forensic")
        assert "[MOOD:" in prompt
        assert SkillsService.get_mood_prompt("neutral") == ""
        assert SkillsService.get_mood_prompt("unknown") == ""

    def test_list_available_moods(self):
        moods = SkillsService.list_available_moods()
        assert "forensic" in moods
        assert "mentor" in moods
        # 7 canonical + legacy aliases
        assert len(moods) >= 7

    def test_create_skill_with_mood(self):
        skill = SkillsService.create_skill(_test_create_req(mood="executor"))
        assert skill.mood == "executor"

    def test_create_skill_invalid_mood_raises(self):
        with pytest.raises(ValueError):
            SkillsService.create_skill(_test_create_req(mood="angry"))

    def test_create_with_tags_and_author(self):
        skill = SkillsService.create_skill(
            _test_create_req(tags=["test", "ci"], author="john", command="/tag-test")
        )
        assert skill.tags == ["test", "ci"]
        assert skill.author == "john"


# ── Auto-Generation Tests ────────────────────────────────────────────────────


class TestAutoGeneration:
    @pytest.mark.asyncio
    async def test_generate_from_prompt_happy_path(self):
        mock_response = {
            "content": json.dumps({
                "name": "Code Analyzer",
                "description": "Analyzes code quality",
                "command": "/auto-analyze",
                "nodes": [
                    {"id": "orch", "type": "orchestrator", "data": {"label": "Orchestrator", "system_prompt": "Drive the analysis", "model": "auto"}, "position": {"x": 0, "y": 0}},
                    {"id": "w1", "type": "worker", "data": {"label": "Analyzer", "system_prompt": "Analyze code", "model": "auto"}, "position": {"x": 250, "y": 0}},
                ],
                "edges": [{"id": "e-orch-w1", "source": "orch", "target": "w1"}],
            })
        }
        with patch("tools.gimo_server.services.provider_service_impl.ProviderService.static_generate", new_callable=AsyncMock, return_value=mock_response):
            req = SkillAutoGenRequest(prompt="Analyze code quality in a repo")
            skill = await SkillsService.generate_skill_from_prompt(req)
            assert skill.name == "Code Analyzer"
            assert skill.command == "/auto-analyze"
            assert len(skill.nodes) == 2
            assert "auto-generated" in skill.tags

    @pytest.mark.asyncio
    async def test_generate_with_markdown_fences(self):
        """LLM sometimes wraps JSON in markdown code fences."""
        raw_json = json.dumps({
            "name": "Fenced Skill",
            "description": "Test",
            "command": "/auto-fenced",
            "nodes": [
                {"id": "orch", "type": "orchestrator", "data": {"label": "O", "system_prompt": "x", "model": "auto"}, "position": {"x": 0, "y": 0}},
            ],
            "edges": [],
        })
        mock_response = {"content": f"```json\n{raw_json}\n```"}
        with patch("tools.gimo_server.services.provider_service_impl.ProviderService.static_generate", new_callable=AsyncMock, return_value=mock_response):
            req = SkillAutoGenRequest(prompt="A simple test skill")
            skill = await SkillsService.generate_skill_from_prompt(req)
            assert skill.name == "Fenced Skill"

    @pytest.mark.asyncio
    async def test_generate_with_mood(self):
        mock_response = {
            "content": json.dumps({
                "name": "Mood Skill",
                "description": "Has mood",
                "command": "/auto-mood",
                "nodes": [
                    {"id": "orch", "type": "orchestrator", "data": {"label": "O", "system_prompt": "", "model": "auto"}, "position": {"x": 0, "y": 0}},
                ],
                "edges": [],
            })
        }
        with patch("tools.gimo_server.services.provider_service_impl.ProviderService.static_generate", new_callable=AsyncMock, return_value=mock_response):
            req = SkillAutoGenRequest(prompt="Skill with forensic mood", mood="forensic")
            skill = await SkillsService.generate_skill_from_prompt(req)
            assert skill.mood == "forensic"
