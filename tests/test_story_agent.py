"""Tests for RuleBasedStoryAgent that `tests/test_story_agent_unit.py` cannot cover.

The 0.60 importance/relevance boundaries, the event_type gate, and both
`needs_human_review` failure reasons are pinned directly and exhaustively in
`tests/test_story_agent_unit.py` -- this file used to duplicate a subset of
that coverage by calling the same methods through the same kind of synthetic
event. What's left here is what the unit file's synthetic-event fixtures
can't exercise:

- routing through `PrototypeOrchestrator` (a low-importance event must never
  reach the media search tool at all, not just be rejected afterwards)
- the exact Japanese strings emitted by default (`RuleBasedStoryAgent()`
  with no language argument), as a literal regression pin independent of
  the structural boundary checks in the unit file
"""

from dataclasses import replace

from app.agents import PrototypeOrchestrator, RuleBasedStoryAgent
from app.contracts import DecisionStatus, MediaAsset, VideoAnalysis
from app.main import build_demo_event
from app.mcp import MockMediaSearchTool
from app.video import MockVideoAnalyzer


def test_low_importance_event_does_not_search_for_media() -> None:
    event = replace(build_demo_event(), event_type="normal_ride", importance_hint=0.2)
    search = MockMediaSearchTool(
        MediaAsset("asset-1", "box", "test_ride_001.mp4", "video/mp4", 30, "box://test")
    )
    analysis = VideoAnalysis(
        "asset-1", 0, 30, "mock", "unknown", (), "unknown", 0.5, 0.8, 0.0, "mock"
    )
    result = PrototypeOrchestrator(RuleBasedStoryAgent(), search, MockVideoAnalyzer(analysis)).run(
        event
    )
    assert result.needs_video_evidence is False
    assert result.decision_status is DecisionStatus.REJECTED
    assert search.calls == 0


def test_needs_human_review_accepts_a_raw_string_failure_value() -> None:
    event = build_demo_event()
    decision = RuleBasedStoryAgent().needs_human_review(event, "missing_asset")  # type: ignore[arg-type]
    assert decision.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    assert decision.reason == "映像証拠が必要だが、対応する素材が見つからない。"


def test_default_output_language_is_japanese() -> None:
    event = replace(build_demo_event(), event_type="normal_ride", importance_hint=0.2)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.reason == "このイベントは映像証拠を必要とする重要度に達していない。"
