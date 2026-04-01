"""Tests for the GIMO Mood Engine (engine/moods.py)."""
import pytest

from tools.gimo_server.engine.moods import (
    LEGACY_MOOD_ALIASES,
    MOOD_PROFILES,
    MOOD_PROMPTS,
    MoodProfile,
    get_mood_profile,
)

EXPECTED_MOODS = {"neutral", "assertive", "calm", "analytical", "exploratory", "cautious", "collaborative", "didactic"}
LEGACY_MOODS = {"neutral", "forensic", "executor", "dialoger", "creative", "guardian", "mentor"}


class TestMoodProfiles:
    def test_all_canonical_profiles_exist(self):
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
            assert isinstance(profile.response_style, str), f"{name} missing response_style"

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

    def test_legacy_aliases_resolve_to_canonical_profiles(self):
        for legacy_name, canonical_name in LEGACY_MOOD_ALIASES.items():
            profile = get_mood_profile(legacy_name)
            assert profile.name == canonical_name

    def test_invalid_mood_raises_key_error(self):
        with pytest.raises(KeyError):
            get_mood_profile("nonexistent_mood")

    def test_empty_string_raises_key_error(self):
        with pytest.raises(KeyError):
            get_mood_profile("")


class TestMoodPromptsBackwardCompat:
    def test_mood_prompts_has_all_canonical_keys(self):
        assert EXPECTED_MOODS.issubset(set(MOOD_PROMPTS.keys()))

    def test_values_match_prompt_prefix(self):
        for name in EXPECTED_MOODS:
            prompt = MOOD_PROMPTS[name]
            assert prompt == MOOD_PROFILES[name].prompt_prefix

    def test_neutral_has_empty_prompt(self):
        assert MOOD_PROMPTS["neutral"] == ""

    def test_legacy_prompt_aliases_exist(self):
        assert LEGACY_MOODS.issubset(set(MOOD_PROMPTS.keys()))
