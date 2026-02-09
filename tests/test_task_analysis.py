"""Tests for task complexity analysis and automatic model preference inference."""

import pytest

from opencode_teams.task_analysis import (
    analyze_task_complexity,
    infer_model_preference,
)
from opencode_teams.models import ModelPreference


class TestAnalyzeTaskComplexity:
    """Tests for analyze_task_complexity function."""

    def test_empty_prompt_returns_low(self):
        """Empty prompts should default to low complexity."""
        assert analyze_task_complexity("") == "low"
        assert analyze_task_complexity("   ") == "low"

    def test_lookup_keywords_return_none(self):
        """Simple lookup/retrieval tasks should return 'none' effort."""
        assert analyze_task_complexity("list all files") == "none"
        assert analyze_task_complexity("show the current status") == "none"
        assert analyze_task_complexity("find the config file") == "none"
        assert analyze_task_complexity("get the user count") == "none"

    def test_low_complexity_keywords(self):
        """Simple fix/update tasks should return 'low' effort."""
        assert analyze_task_complexity("fix the typo in README") == "low"
        assert analyze_task_complexity("rename variable foo to bar") == "low"
        assert analyze_task_complexity("format the code") == "low"
        assert analyze_task_complexity("delete unused imports") == "low"

    def test_medium_complexity_keywords(self):
        """Implementation tasks should return 'medium' effort."""
        assert analyze_task_complexity("implement the login feature") == "medium"
        assert analyze_task_complexity("add user authentication") == "medium"
        assert analyze_task_complexity("create a new endpoint") == "medium"
        assert analyze_task_complexity("test the payment flow") == "medium"

    def test_high_complexity_keywords(self):
        """Architecture/analysis tasks should return 'high' effort."""
        assert analyze_task_complexity("architect the new microservices") == "high"
        assert analyze_task_complexity("analyze the performance issues") == "high"
        assert analyze_task_complexity("debug the memory leak") == "high"
        assert analyze_task_complexity("investigate the race condition") == "high"
        assert analyze_task_complexity("research caching strategies") == "high"

    def test_length_increases_complexity(self):
        """Longer prompts should increase complexity level."""
        # Short high-complexity task stays high
        short_prompt = "debug the issue"
        assert analyze_task_complexity(short_prompt) == "high"

        # Very long prompt (>500 words) should push to xhigh
        long_prompt = "debug " + " ".join(["word"] * 600)
        assert analyze_task_complexity(long_prompt) == "xhigh"

    def test_complexity_patterns_increase_score(self):
        """Patterns like 'multiple files' should increase complexity."""
        # Base medium task
        base = "implement feature"
        assert analyze_task_complexity(base) == "medium"

        # With complexity pattern - bumps to high
        with_pattern = "implement feature across multiple files in the codebase"
        assert analyze_task_complexity(with_pattern) == "high"

        # Another pattern
        conditional = "implement feature depending on the user type"
        assert analyze_task_complexity(conditional) == "high"

    def test_multiple_patterns_stack(self):
        """Multiple complexity patterns should stack."""
        # This has: high keyword (analyze) + multiple patterns
        complex_prompt = (
            "analyze the integration end-to-end across the codebase "
            "with careful attention to edge cases"
        )
        result = analyze_task_complexity(complex_prompt)
        assert result in ("high", "xhigh")

    def test_no_keywords_defaults_to_medium(self):
        """Prompts without recognized keywords default to medium."""
        # Gibberish with no keywords
        assert analyze_task_complexity("lorem ipsum dolor sit amet") == "medium"

    def test_keyword_matching_is_case_insensitive(self):
        """Keywords should match regardless of case."""
        assert analyze_task_complexity("ARCHITECT the system") == "high"
        assert analyze_task_complexity("Debug THE ISSUE") == "high"
        assert analyze_task_complexity("List Files") == "none"


class TestInferModelPreference:
    """Tests for infer_model_preference function."""

    def test_no_explicit_preference_uses_inference(self):
        """Without explicit preference, should fully infer from prompt."""
        pref = infer_model_preference("debug the memory leak")
        assert pref.reasoning_effort == "high"

        pref = infer_model_preference("list all users")
        assert pref.reasoning_effort == "none"
        assert pref.prefer_speed is True  # Lookup tasks default to speed

    def test_explicit_reasoning_effort_overrides_inference(self):
        """Explicit reasoning_effort should override inferred value."""
        # High-complexity prompt but explicit low effort
        explicit = ModelPreference(reasoning_effort="low")
        pref = infer_model_preference("architect the entire system", explicit=explicit)
        assert pref.reasoning_effort == "low"

        # Low-complexity prompt but explicit high effort
        explicit = ModelPreference(reasoning_effort="high")
        pref = infer_model_preference("fix typo", explicit=explicit)
        assert pref.reasoning_effort == "high"

    def test_explicit_prefer_speed_preserved(self):
        """Explicit prefer_speed should be preserved."""
        explicit = ModelPreference(prefer_speed=True)
        pref = infer_model_preference("architect the system", explicit=explicit)
        assert pref.prefer_speed is True

        explicit = ModelPreference(prefer_speed=False)
        pref = infer_model_preference("list files", explicit=explicit)
        # Even for lookup tasks, explicit False is preserved
        assert pref.prefer_speed is False

    def test_other_explicit_fields_preserved(self):
        """Other ModelPreference fields should be preserved."""
        explicit = ModelPreference(
            min_context_window=100000,
            required_modalities=["text", "image"],
            provider="openai",
        )
        pref = infer_model_preference("implement feature", explicit=explicit)

        assert pref.min_context_window == 100000
        assert pref.required_modalities == ["text", "image"]
        assert pref.provider == "openai"
        assert pref.reasoning_effort == "medium"  # Inferred from prompt

    def test_partial_explicit_merges_with_inference(self):
        """Partial explicit preference should merge with inference."""
        # Only prefer_speed set explicitly
        explicit = ModelPreference(prefer_speed=True)
        pref = infer_model_preference("analyze performance", explicit=explicit)

        assert pref.reasoning_effort == "high"  # Inferred
        assert pref.prefer_speed is True  # Explicit

    def test_none_explicit_is_same_as_no_explicit(self):
        """Passing None for explicit should be same as not passing it."""
        pref1 = infer_model_preference("debug issue", explicit=None)
        pref2 = infer_model_preference("debug issue")

        assert pref1.reasoning_effort == pref2.reasoning_effort
        assert pref1.prefer_speed == pref2.prefer_speed


class TestEdgeCases:
    """Edge case tests."""

    def test_very_long_prompt(self):
        """Very long prompts should not crash and should return high/xhigh."""
        long_prompt = "analyze " + " ".join(["complexity"] * 1000)
        result = analyze_task_complexity(long_prompt)
        assert result == "xhigh"

    def test_unicode_content(self):
        """Unicode content should be handled gracefully."""
        # Japanese: "Please fix the bug"
        prompt = "バグを修正してください fix the bug"
        result = analyze_task_complexity(prompt)
        assert result == "low"  # Should still match "fix"

    def test_special_characters(self):
        """Prompts with special characters should not crash."""
        prompt = "fix the bug in file.py#L42 && run tests"
        result = analyze_task_complexity(prompt)
        assert result == "low"

    def test_newlines_in_prompt(self):
        """Multi-line prompts should be analyzed correctly."""
        prompt = """
        Please investigate the following issue:
        - Users are seeing errors
        - The database connection times out
        - Multiple services are affected
        """
        result = analyze_task_complexity(prompt)
        assert result == "high"  # "investigate" is high complexity

    def test_repeated_keywords_dont_stack(self):
        """Repeated keywords shouldn't artificially inflate score."""
        # "debug debug debug" shouldn't be higher than "debug"
        single = analyze_task_complexity("debug the issue")
        repeated = analyze_task_complexity("debug debug debug the issue")
        assert single == repeated
