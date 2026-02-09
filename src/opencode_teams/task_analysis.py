"""Task complexity analysis for automatic model selection.

Analyzes task prompts to infer appropriate reasoning effort levels,
enabling automatic model selection without manual configuration.
"""
from __future__ import annotations

import re
from typing import Literal

from opencode_teams.models import ModelPreference

# Reasoning effort levels ordered from lowest to highest
EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh")

# Keywords associated with each complexity level
# More specific/longer phrases should be matched first
HIGH_COMPLEXITY_KEYWORDS = frozenset({
    # Architecture & design
    "architect", "architecture", "design", "redesign", "refactor",
    "restructure", "migrate", "migration",
    # Deep analysis
    "analyze", "analysis", "investigate", "debug", "diagnose",
    "troubleshoot", "trace", "profile", "optimize", "performance",
    # Research & exploration
    "research", "explore", "evaluate", "compare", "assess",
    "audit", "review", "security",
    # Complex planning
    "plan", "strategy", "roadmap", "propose",
})

MEDIUM_COMPLEXITY_KEYWORDS = frozenset({
    # Implementation
    "implement", "build", "develop", "create", "integrate",
    "connect", "configure", "setup", "install",
    # Feature work
    "add", "extend", "enhance", "improve", "upgrade",
    # Testing
    "test", "verify", "validate", "check",
    # Documentation
    "document", "explain", "describe",
})

LOW_COMPLEXITY_KEYWORDS = frozenset({
    # Simple changes
    "fix", "patch", "update", "change", "modify", "edit",
    "rename", "move", "copy", "delete", "remove",
    # Formatting
    "format", "lint", "style", "clean", "tidy",
    # Simple additions
    "add", "insert", "append",
})

LOOKUP_KEYWORDS = frozenset({
    # Pure retrieval
    "list", "show", "display", "print", "get", "fetch",
    "find", "search", "locate", "read", "view",
    "count", "check", "status",
})

# Patterns that suggest higher complexity
COMPLEXITY_PATTERNS = [
    # Multiple files mentioned
    (re.compile(r"\bmultiple\s+(files?|components?|modules?)\b", re.I), 1),
    (re.compile(r"\b(across|throughout)\s+(the\s+)?(codebase|project|repo)\b", re.I), 1),
    # Cross-cutting concerns
    (re.compile(r"\b(end-to-end|e2e|integration)\b", re.I), 1),
    # Conditional/branching logic
    (re.compile(r"\bif\s+.+\s+(then|else|otherwise)\b", re.I), 1),
    (re.compile(r"\b(depending\s+on|based\s+on|conditional)\b", re.I), 1),
    # Complexity indicators
    (re.compile(r"\b(complex|complicated|intricate|nuanced)\b", re.I), 1),
    (re.compile(r"\b(careful|thorough|comprehensive)\b", re.I), 1),
]


def _count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def _find_keyword_match(
    text: str, keywords: frozenset[str]
) -> str | None:
    """Find the first keyword that matches in the text (case-insensitive)."""
    text_lower = text.lower()
    for kw in keywords:
        # Match as whole word
        if re.search(rf"\b{re.escape(kw)}\b", text_lower):
            return kw
    return None


def analyze_task_complexity(
    prompt: str,
) -> Literal["none", "low", "medium", "high", "xhigh"]:
    """Analyze a task prompt to determine required reasoning effort.

    Uses keyword matching, prompt length, and pattern analysis to infer
    the complexity level of a task.

    Args:
        prompt: The task description/prompt to analyze.

    Returns:
        Recommended reasoning effort level: "none", "low", "medium", "high", or "xhigh".

    Scoring:
        - Base score from keyword matching (lookup=0, low=1, medium=2, high=3)
        - Bonus for length (long prompts suggest complexity)
        - Bonus for complexity patterns
        - Final score mapped to effort level
    """
    if not prompt or not prompt.strip():
        return "low"  # Default for empty prompts

    # Start with base score
    score = 0

    # Check keywords in order of specificity (high -> medium -> low -> lookup)
    if _find_keyword_match(prompt, HIGH_COMPLEXITY_KEYWORDS):
        score = 3
    elif _find_keyword_match(prompt, MEDIUM_COMPLEXITY_KEYWORDS):
        score = 2
    elif _find_keyword_match(prompt, LOW_COMPLEXITY_KEYWORDS):
        score = 1
    elif _find_keyword_match(prompt, LOOKUP_KEYWORDS):
        score = 0
    else:
        # No clear keywords - use medium as default
        score = 2

    # Length bonus
    word_count = _count_words(prompt)
    if word_count > 500:
        score += 2  # Very long prompt suggests complexity
    elif word_count > 200:
        score += 1  # Moderately long

    # Pattern bonuses
    for pattern, bonus in COMPLEXITY_PATTERNS:
        if pattern.search(prompt):
            score += bonus

    # Map score to effort level
    # 0 -> none, 1 -> low, 2 -> medium, 3-4 -> high, 5+ -> xhigh
    if score <= 0:
        return "none"
    elif score == 1:
        return "low"
    elif score == 2:
        return "medium"
    elif score <= 4:
        return "high"
    else:
        return "xhigh"


def infer_model_preference(
    prompt: str,
    explicit: ModelPreference | None = None,
) -> ModelPreference:
    """Combine task analysis with explicit preferences.

    Explicit preferences always override inferred values. If a preference
    field is not explicitly set, it will be inferred from the prompt.

    Args:
        prompt: The task description/prompt to analyze.
        explicit: Explicitly provided preferences (these override inference).

    Returns:
        ModelPreference with inferred values filled in where explicit values
        are not provided.
    """
    # Infer reasoning effort from prompt
    inferred_effort = analyze_task_complexity(prompt)

    # Infer prefer_speed: True for lookup/none tasks
    inferred_prefer_speed = inferred_effort == "none"

    # If no explicit preference provided, return fully inferred
    if explicit is None:
        return ModelPreference(
            reasoning_effort=inferred_effort,
            prefer_speed=inferred_prefer_speed,
        )

    # Explicit values override inferred values
    # Only use inferred effort if explicit effort is not set
    final_effort = explicit.reasoning_effort if explicit.reasoning_effort else inferred_effort

    # For prefer_speed: explicit True/False wins, but we need to detect if it was
    # actually set by the user vs just defaulting to False.
    # Since ModelPreference.prefer_speed defaults to False, we check if the user
    # explicitly passed a non-None ModelPreference - if so, honor their prefer_speed.
    # The explicit ModelPreference's prefer_speed value should be used as-is.
    final_prefer_speed = explicit.prefer_speed

    return ModelPreference(
        reasoning_effort=final_effort,
        min_context_window=explicit.min_context_window,
        required_modalities=explicit.required_modalities,
        provider=explicit.provider,
        prefer_speed=final_prefer_speed,
    )
