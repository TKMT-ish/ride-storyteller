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
    result = PrototypeOrchestrator(
        RuleBasedStoryAgent(), search, MockVideoAnalyzer(analysis)
    ).run(event)
    assert result.needs_video_evidence is False
    assert result.decision_status is DecisionStatus.REJECTED
    assert search.calls == 0
