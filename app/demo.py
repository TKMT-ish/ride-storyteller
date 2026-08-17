"""Synthetic-only demo data and agent runs for the local UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.agents import (
    PrototypeOrchestrator,
    RuleBasedStoryAgent,
    RuleBasedStoryPlanner,
    StoryOutputLanguage,
)
from app.contracts import (
    GpsEvent,
    Location,
    MediaAsset,
    RouteSummary,
    StoryDecision,
    StoryPlan,
    VideoAnalysis,
    VideoQuery,
)
from app.edit import (
    CandidateEditPlan,
    CandidateEditReview,
    build_candidate_edit_plan,
    review_candidate_edit_plan,
)
from app.mcp import MockMediaSearchTool
from app.video import GeminiVideoAnalyzer, MockVideoAnalyzer


@dataclass(frozen=True)
class DemoRun:
    scenario: str
    label: str
    decision: StoryDecision
    steps: tuple[str, ...]


SCENARIO_LABELS = {
    StoryOutputLanguage.JAPANESE: {
        "accepted": "映像証拠により採用",
        "rejected": "映像証拠により不採用",
        "missing_asset": "対応する素材が見つからない",
        "gemini_unavailable": "Gemini映像解析が利用できない",
    },
    StoryOutputLanguage.ENGLISH: {
        "accepted": "Accepted with video evidence",
        "rejected": "Rejected after video evidence",
        "missing_asset": "Matching media not found",
        "gemini_unavailable": "Gemini video analysis unavailable",
    },
}
DEMO_STEPS = {
    StoryOutputLanguage.JAPANESE: (
        "GPSイベントを受信",
        "Story Agentが映像証拠の要否を判断",
        "素材検索",
        "映像解析または人手確認への切替",
        "Story Agentが最終判断",
    ),
    StoryOutputLanguage.ENGLISH: (
        "Receive the GPS event",
        "The Story Agent decides whether video evidence is required",
        "Search for matching media",
        "Analyze the clip or fail safely to human review",
        "The Story Agent makes the final decision",
    ),
}


def build_demo_event() -> GpsEvent:
    return GpsEvent(
        event_id="evt_sample_001",
        event_type="scenery_change",
        start_time=datetime(2026, 8, 10, 1, 42, 15, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 1, 43, 0, tzinfo=UTC),
        location=Location(latitude=-45.0312, longitude=168.6626),
        importance_hint=0.72,
        evidence=("elevation_change", "direction_change"),
        video_query=VideoQuery("test_ride_001.mp4", 0, 30),
    )


def run_demo(
    scenario: str = "accepted",
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
) -> DemoRun:
    output_language = StoryOutputLanguage(output_language)
    if scenario not in SCENARIO_LABELS[output_language]:
        raise ValueError(f"unknown demo scenario: {scenario}")

    asset = _asset()
    search = MockMediaSearchTool(None if scenario == "missing_asset" else asset)
    if scenario == "gemini_unavailable":
        analyzer = GeminiVideoAnalyzer(_UnavailableTransport())
    else:
        relevance = 0.30 if scenario == "rejected" else 0.80
        analyzer = MockVideoAnalyzer(_analysis(asset, relevance))

    decision = PrototypeOrchestrator(RuleBasedStoryAgent(output_language), search, analyzer).run(
        build_demo_event()
    )
    return DemoRun(
        scenario=scenario,
        label=SCENARIO_LABELS[output_language][scenario],
        decision=decision,
        steps=DEMO_STEPS[output_language],
    )


def build_demo_story_plan(
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
) -> StoryPlan:
    summary, events = build_demo_story_inputs()
    return RuleBasedStoryPlanner().plan(
        summary,
        events,
        target_duration_s=480,
        output_language=output_language,
    )


def build_demo_story_inputs() -> tuple[RouteSummary, tuple[GpsEvent, ...]]:
    event = build_demo_event()
    departure = GpsEvent(
        event_id="evt_demo_departure",
        event_type="departure",
        start_time=event.start_time,
        end_time=event.start_time,
        location=event.location,
        importance_hint=0.55,
        evidence=("route_start",),
        video_query=event.video_query,
    )
    arrival = GpsEvent(
        event_id="evt_demo_arrival",
        event_type="arrival_candidate",
        start_time=datetime(2026, 8, 10, 5, 42, 15, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 5, 42, 15, tzinfo=UTC),
        location=event.location,
        importance_hint=0.75,
        evidence=("route_end",),
        video_query=event.video_query,
    )
    summary = RouteSummary(
        point_count=4,
        start_time=departure.start_time,
        end_time=arrival.end_time,
        total_distance_m=123_400,
        duration_s=14_400,
        elevation_gain_m=800,
        elevation_loss_m=790,
    )
    return summary, (departure, event, arrival)


def build_demo_candidate_edit_plan(
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
) -> tuple[CandidateEditPlan, CandidateEditReview]:
    """Create a deliberately incomplete plan from synthetic inputs only."""
    summary, events = build_demo_story_inputs()
    story_plan = RuleBasedStoryPlanner().plan(
        summary,
        events,
        target_duration_s=480,
        output_language=output_language,
    )
    plan = build_candidate_edit_plan(story_plan, events)
    return plan, review_candidate_edit_plan(plan)


def _asset() -> MediaAsset:
    return MediaAsset(
        asset_id="box_file_placeholder_001",
        provider="box",
        name="test_ride_001.mp4",
        mime_type="video/mp4",
        duration_s=30,
        source_uri="box://placeholder/test_ride_001.mp4",
    )


def _analysis(asset: MediaAsset, relevance: float) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id=asset.asset_id,
        start_offset_s=0,
        end_offset_s=30,
        visual_description="テスト映像の説明（モック）",
        road_type="unknown",
        scenery_tags=("test",),
        weather_visible="unknown",
        visual_interest_score=0.5,
        story_relevance_score=relevance,
        confidence=0.0,
        analysis_provider="mock",
    )


class _UnavailableTransport:
    def analyze_clip(
        self,
        *,
        source_uri: str,
        mime_type: str,
        start_s: float,
        end_s: float,
        prompt: str,
    ) -> dict[str, object]:
        raise ConnectionError("synthetic unavailable Gemini transport")
