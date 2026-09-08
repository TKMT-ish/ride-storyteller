from dataclasses import replace

import pytest

from app.agents import PrototypeOrchestrator, RuleBasedStoryAgent
from app.agents.story_agent import StoryEvidenceFailure
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


def _analysis(story_relevance_score: float) -> VideoAnalysis:
    return VideoAnalysis(
        "asset-1", 0, 30, "mock", "unknown", (), "unknown", 0.5, story_relevance_score, 0.0, "mock"
    )


def test_decide_from_event_at_the_exact_importance_threshold_needs_evidence() -> None:
    event = replace(build_demo_event(), event_type="scenery_change", importance_hint=0.60)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.needs_video_evidence is True
    assert decision.decision_status is DecisionStatus.AWAITING_VIDEO_EVIDENCE


def test_decide_from_event_just_below_the_importance_threshold_is_rejected() -> None:
    event = replace(build_demo_event(), event_type="scenery_change", importance_hint=0.5999)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.needs_video_evidence is False
    assert decision.decision_status is DecisionStatus.REJECTED
    assert decision.asset_name_hint is None


def test_decide_from_event_ignores_high_importance_of_an_unlisted_event_type() -> None:
    event = replace(build_demo_event(), event_type="normal_ride", importance_hint=0.99)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.needs_video_evidence is False
    assert decision.decision_status is DecisionStatus.REJECTED


@pytest.mark.parametrize("event_type", ("scenery_change", "arrival_candidate", "elevation_change"))
def test_every_evidence_event_type_needs_evidence_at_threshold(event_type: str) -> None:
    event = replace(build_demo_event(), event_type=event_type, importance_hint=0.60)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.needs_video_evidence is True


def test_update_with_video_at_the_exact_relevance_threshold_is_accepted() -> None:
    event = replace(build_demo_event(), event_type="scenery_change", importance_hint=0.60)
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(event)
    updated = agent.update_with_video(decision, _analysis(0.60))
    assert updated.decision_status is DecisionStatus.ACCEPTED
    assert updated.updated_story_role is not None


def test_update_with_video_just_below_the_relevance_threshold_is_rejected() -> None:
    event = replace(build_demo_event(), event_type="scenery_change", importance_hint=0.60)
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(event)
    updated = agent.update_with_video(decision, _analysis(0.5999))
    assert updated.decision_status is DecisionStatus.REJECTED
    assert updated.needs_video_evidence is True
    assert updated.updated_story_role is None


def test_needs_human_review_accepts_a_raw_string_failure_value() -> None:
    event = build_demo_event()
    decision = RuleBasedStoryAgent().needs_human_review(event, "missing_asset")  # type: ignore[arg-type]
    assert decision.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    assert decision.reason == "映像証拠が必要だが、対応する素材が見つからない。"


def test_needs_human_review_rejects_an_unknown_failure_value() -> None:
    event = build_demo_event()
    with pytest.raises(ValueError):
        RuleBasedStoryAgent().needs_human_review(event, "not_a_real_failure")  # type: ignore[arg-type]


def test_needs_human_review_covers_both_failure_reasons() -> None:
    event = build_demo_event()
    agent = RuleBasedStoryAgent()
    missing = agent.needs_human_review(event, StoryEvidenceFailure.MISSING_ASSET)
    unavailable = agent.needs_human_review(event, StoryEvidenceFailure.ANALYSIS_UNAVAILABLE)
    assert missing.reason != unavailable.reason
    assert missing.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    assert unavailable.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW


def test_default_output_language_is_japanese() -> None:
    event = replace(build_demo_event(), event_type="normal_ride", importance_hint=0.2)
    decision = RuleBasedStoryAgent().decide_from_event(event)
    assert decision.reason == "このイベントは映像証拠を必要とする重要度に達していない。"
