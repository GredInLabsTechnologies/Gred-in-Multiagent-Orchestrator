"""Tests for the GIMO Mood Engine (engine/moods.py)."""
import pytest

from tools.gimo_server.engine.moods import (
    MOOD_PROFILES,
    MOOD_PROMPTS,
    MoodProfile,
    get_mood_profile,
)

EXPECTED_MOODS = {"neutral", "forensic", "executor", "dialoger", "creative", "guardian", "mentor"}


class TestMoodProfiles:
    def test_all_seven_profiles_exist(self):
        assert set(MOOD_PROFILES.keys()) == EXPECTED_MOODS

    def test_profiles_are_mood_profile_instances(self):
        for name, profile in MOOD_PROFILES.items():
            assert isinstance(profile, MoodProfile), f"{name} is not a MoodProfile"

    def test_profile_name_matches_key(self):
        for key, profile in MOOD_PROFILES.items():
            assert profile.name == key

    def test_required_fields_present(self):
        for name, profile in MOOD_PROFILES.items():
            assert isinstance(profile.prompt_prefix, str), f"{name} missing prompt_prefix"
            assert isinstance(profile.temperature, (int, float)), f"{name} missing temperature"
            assert isinstance(profile.max_turns, int), f"{name} missing max_turns"
            assert isinstance(profile.tool_whitelist, set), f"{name} missing tool_whitelist"
            assert isinstance(profile.tool_blacklist, set), f"{name} missing tool_blacklist"
            assert isinstance(profile.requires_confirmation, set), f"{name} missing requires_confirmation"
            assert isinstance(profile.response_style, str), f"{name} missing response_style"
            assert isinstance(profile.auto_transition_to, str), f"{name} missing auto_transition_to"

    def test_temperature_in_range(self):
        for name, profile in MOOD_PROFILES.items():
            assert 0.0 <= profile.temperature <= 1.0, f"{name} temperature {profile.temperature} out of [0,1]"

    def test_max_turns_positive(self):
        for name, profile in MOOD_PROFILES.items():
            assert profile.max_turns > 0, f"{name} max_turns must be > 0"

    def test_profiles_are_frozen(self):
        profile = MOOD_PROFILES["neutral"]
        with pytest.raises(AttributeError):
            profile.temperature = 0.5  # type: ignore[misc]


class TestGetMoodProfile:
    def test_returns_correct_profile(self):
        for mood in EXPECTED_MOODS:
            profile = get_mood_profile(mood)
            assert profile.name == mood

    def test_invalid_mood_raises_key_error(self):
        with pytest.raises(KeyError):
            get_mood_profile("nonexistent_mood")

    def test_empty_string_raises_key_error(self):
        with pytest.raises(KeyError):
            get_mood_profile("")


class TestMoodPromptsBackwardCompat:
    def test_mood_prompts_has_all_keys(self):
        assert set(MOOD_PROMPTS.keys()) == EXPECTED_MOODS

    def test_values_match_prompt_prefix(self):
        for name, prompt in MOOD_PROMPTS.items():
            assert prompt == MOOD_PROFILES[name].prompt_prefix

    def test_neutral_has_empty_prompt(self):
        assert MOOD_PROMPTS["neutral"] == ""
