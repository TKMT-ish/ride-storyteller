"""Dependency-free verification for constrained development environments.

The pytest suite remains the normal developer test suite. This script covers
the Day 1 acceptance behaviour when third-party packages cannot be installed.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.agents import PrototypeOrchestrator, RuleBasedStoryAgent
from app.contracts import DecisionStatus, GpsEvent, Location, MediaAsset, VideoAnalysis, VideoQuery
from app.main import build_demo_event
from app.mcp import MockMediaSearchTool
from app.video import MockVideoAnalyzer


def asset() -> MediaAsset:
    return MediaAsset("asset-1", "box", "test_ride_001.mp4", "video/mp4", 30, "box://test")


def analysis(score: float) -> VideoAnalysis:
    return VideoAnalysis(
        "asset-1", 0, 30, "mock", "unknown", ("test",), "unknown", 0.5, score, 0.0, "mock"
    )


def main() -> None:
    # Contracts reject bad values.
    try:
        GpsEvent(
            "evt-invalid", "scenery_change", datetime(2026, 8, 10, tzinfo=UTC),
            datetime(2026, 8, 10, 0, 1, tzinfo=UTC), Location(0, 0), 1.2, (),
            VideoQuery("fixture.mp4", 0, 1),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range importance score was accepted")

    # High-importance event: Story Agent initiates a full evidence loop.
    search = MockMediaSearchTool(asset())
    analyzer = MockVideoAnalyzer(analysis(0.8))
    result = PrototypeOrchestrator(RuleBasedStoryAgent(), search, analyzer).run(build_demo_event())
    assert result.decision_status is DecisionStatus.ACCEPTED
    assert result.updated_story_role
    assert search.calls == 1 and analyzer.calls == 1

    # Low-importance event: no external search is made.
    low_event = replace(build_demo_event(), event_type="normal_ride", importance_hint=0.2)
    search = MockMediaSearchTool(asset())
    result = PrototypeOrchestrator(
        RuleBasedStoryAgent(), search, MockVideoAnalyzer(analysis(0.8))
    ).run(low_event)
    assert result.needs_video_evidence is False and search.calls == 0

    # Missing media stays safe and reviewable; low relevance is rejected.
    missing = PrototypeOrchestrator(
        RuleBasedStoryAgent(), MockMediaSearchTool(None), MockVideoAnalyzer(analysis(0.8))
    ).run(build_demo_event())
    assert missing.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    rejected = PrototypeOrchestrator(
        RuleBasedStoryAgent(), MockMediaSearchTool(asset()), MockVideoAnalyzer(analysis(0.3))
    ).run(build_demo_event())
    assert rejected.decision_status is DecisionStatus.REJECTED

    ignored = Path(".gitignore").read_text()
    assert all(item in ignored for item in (".env", "*.gpx", "*.fit", "*.mp4", "*.mov", "*.lrv"))
    print("Day 1 dependency-free checks: passed")


if __name__ == "__main__":
    main()
