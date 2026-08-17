from dataclasses import replace

from app.agents import PrototypeOrchestrator, RuleBasedStoryAgent
from app.contracts import DecisionStatus, MediaAsset, VideoAnalysis
from app.main import build_demo_event
from app.mcp import MockMediaSearchTool
from app.video import MockVideoAnalyzer


def _asset() -> MediaAsset:
    return MediaAsset("asset-1", "box", "test_ride_001.mp4", "video/mp4", 30, "box://test")


def _analysis(score: float) -> VideoAnalysis:
    return VideoAnalysis(
        "asset-1", 0, 30, "mock", "unknown", ("test",), "unknown", 0.5, score, 0.0, "mock"
    )


def test_high_importance_event_runs_full_loop_and_is_accepted() -> None:
    search = MockMediaSearchTool(_asset())
    analyzer = MockVideoAnalyzer(_analysis(0.8))
    result = PrototypeOrchestrator(RuleBasedStoryAgent(), search, analyzer).run(build_demo_event())
    assert result.decision_status is DecisionStatus.ACCEPTED
    assert result.updated_story_role
    assert search.calls == 1
    assert analyzer.calls == 1


def test_missing_asset_requires_human_review() -> None:
    result = PrototypeOrchestrator(
        RuleBasedStoryAgent(), MockMediaSearchTool(None), MockVideoAnalyzer(_analysis(0.8))
    ).run(build_demo_event())
    assert result.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW


def test_low_relevance_video_is_rejected() -> None:
    result = PrototypeOrchestrator(
        RuleBasedStoryAgent(), MockMediaSearchTool(_asset()), MockVideoAnalyzer(_analysis(0.3))
    ).run(build_demo_event())
    assert result.decision_status is DecisionStatus.REJECTED


def test_unknown_event_type_fails_closed_without_media_calls() -> None:
    search = MockMediaSearchTool(_asset())
    analyzer = MockVideoAnalyzer(_analysis(0.8))
    unknown = replace(build_demo_event(), event_type="future_unknown_event")

    result = PrototypeOrchestrator(RuleBasedStoryAgent(), search, analyzer).run(unknown)

    assert result.decision_status is DecisionStatus.REJECTED
    assert result.needs_video_evidence is False
    assert search.calls == 0
    assert analyzer.calls == 0
