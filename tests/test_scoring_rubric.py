"""The judging prompt names what separates an ordinary window from one worth showing.

The first real ride was judged without a rubric and came back flat: a
third of the windows at exactly one score, a third at exactly another.
These hold that the prompt now carries anchors for both scores, asks for
the whole range, and still describes only what is visible.
"""

from __future__ import annotations

from app.video.gemini_client import SCORING_RUBRIC, _analysis_prompt


def test_the_prompt_carries_the_rubric_and_the_interval() -> None:
    prompt = _analysis_prompt(1830.0, 1842.0)

    assert SCORING_RUBRIC in prompt
    assert "Requested interval: 1830.00s to 1842.00s." in prompt
    assert "Describe only visually supported facts" in prompt


def test_both_scores_have_anchors_across_the_range() -> None:
    for score in ("visual_interest_score", "story_relevance_score", "photogenic_score"):
        assert score in SCORING_RUBRIC
    for anchor in ("0.2 =", "0.5 =", "0.8 =", "1.0 ="):
        assert SCORING_RUBRIC.count(anchor) == 3, anchor


def test_the_rubric_asks_for_the_whole_range_and_reserves_the_top() -> None:
    assert "whole range" in SCORING_RUBRIC
    assert "above 0.7" in SCORING_RUBRIC
    assert "ordinary" in SCORING_RUBRIC


def test_the_anchors_name_what_a_road_looks_like_not_abstractions() -> None:
    """A model can act on \"a gorge\" and \"a queue of traffic\"; not on \"quality\"."""
    for concrete in ("car park", "queue of traffic", "gorge", "curves", "summit", "arrival"):
        assert concrete in SCORING_RUBRIC
