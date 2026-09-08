"""Boundary and failure-path tests for the Day 1 data contracts.

Held: every dataclass in `app.contracts` refuses the shape it says it refuses
(naive timestamps, out-of-order times, out-of-range scores, missing required
text) and accepts the shape at its own boundary (a score of exactly 0.0 or
1.0, a latitude of exactly 90). The `to_dict()` methods are the only place
these values leave the process as JSON-shaped data, so their timestamp
formatting is pinned here too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import (
    DecisionStatus,
    GpsEvent,
    Location,
    MediaAsset,
    RetrievalStatus,
    RoutePoint,
    RouteSummary,
    StoryChapter,
    StoryDecision,
    StoryPlan,
    VideoAnalysis,
    VideoQuery,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "latitude,longitude",
    [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
)
def test_location_accepts_its_own_boundary(latitude: float, longitude: float) -> None:
    location = Location(latitude, longitude)
    assert location.latitude == latitude
    assert location.longitude == longitude


@pytest.mark.parametrize(
    "latitude,longitude",
    [(90.0001, 0.0), (-90.0001, 0.0), (0.0, 180.0001), (0.0, -180.0001)],
)
def test_location_rejects_just_past_its_boundary(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError, match="latitude|longitude"):
        Location(latitude, longitude)


# ---------------------------------------------------------------------------
# RoutePoint
# ---------------------------------------------------------------------------


def test_route_point_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RoutePoint(
            timestamp=datetime(2026, 5, 1, 9, 0, 0),
            latitude=0.0,
            longitude=0.0,
            elevation_m=None,
            distance_from_start_m=0.0,
            speed_mps=None,
        )


def test_route_point_rejects_a_negative_distance() -> None:
    with pytest.raises(ValueError, match="distance_from_start_m"):
        RoutePoint(
            timestamp=_T0,
            latitude=0.0,
            longitude=0.0,
            elevation_m=None,
            distance_from_start_m=-1.0,
            speed_mps=None,
        )


def test_route_point_rejects_a_negative_speed() -> None:
    with pytest.raises(ValueError, match="speed_mps"):
        RoutePoint(
            timestamp=_T0,
            latitude=0.0,
            longitude=0.0,
            elevation_m=None,
            distance_from_start_m=0.0,
            speed_mps=-0.1,
        )


def test_route_point_rejects_an_out_of_range_coordinate() -> None:
    with pytest.raises(ValueError, match="latitude|longitude"):
        RoutePoint(
            timestamp=_T0,
            latitude=91.0,
            longitude=0.0,
            elevation_m=None,
            distance_from_start_m=0.0,
            speed_mps=None,
        )


def test_route_point_to_dict_writes_zulu_and_keeps_optional_fields_none() -> None:
    point = RoutePoint(
        timestamp=_T0,
        latitude=35.0,
        longitude=139.0,
        elevation_m=None,
        distance_from_start_m=12.5,
        speed_mps=None,
    )
    data = point.to_dict()
    assert data["timestamp"] == "2026-05-01T09:00:00Z"
    assert data["elevation_m"] is None
    assert data["speed_mps"] is None
    assert data["distance_from_start_m"] == 12.5


# ---------------------------------------------------------------------------
# RouteSummary
# ---------------------------------------------------------------------------


def _summary(**overrides: object) -> RouteSummary:
    fields: dict[str, object] = {
        "point_count": 10,
        "start_time": _T0,
        "end_time": _T0 + timedelta(hours=1),
        "total_distance_m": 1000.0,
        "duration_s": 3600.0,
        "elevation_gain_m": 50.0,
        "elevation_loss_m": 40.0,
    }
    fields.update(overrides)
    return RouteSummary(**fields)  # type: ignore[arg-type]


def test_route_summary_rejects_a_non_positive_point_count() -> None:
    with pytest.raises(ValueError, match="point_count"):
        _summary(point_count=0)


def test_route_summary_rejects_a_naive_start_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _summary(start_time=datetime(2026, 5, 1, 9, 0, 0))


def test_route_summary_rejects_a_naive_end_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _summary(end_time=datetime(2026, 5, 1, 10, 0, 0))


def test_route_summary_rejects_an_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_time"):
        _summary(end_time=_T0 - timedelta(seconds=1))


@pytest.mark.parametrize(
    "field",
    ["total_distance_m", "duration_s", "elevation_gain_m", "elevation_loss_m"],
)
def test_route_summary_rejects_any_negative_measurement(field: str) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _summary(**{field: -1.0})


def test_route_summary_to_dict_writes_zulu_for_both_times() -> None:
    data = _summary().to_dict()
    assert data["start_time"] == "2026-05-01T09:00:00Z"
    assert data["end_time"] == "2026-05-01T10:00:00Z"


# ---------------------------------------------------------------------------
# StoryChapter
# ---------------------------------------------------------------------------


def _chapter(**overrides: object) -> StoryChapter:
    fields: dict[str, object] = {
        "chapter_id": "ch_1",
        "title": "Departure",
        "event_id": "evt_1",
        "start_time": _T0,
        "end_time": _T0 + timedelta(minutes=5),
        "narrative_role": "opening",
        "selection_rationale": "highest ranked window",
        "target_duration_s": 30.0,
    }
    fields.update(overrides)
    return StoryChapter(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    ["chapter_id", "title", "event_id", "narrative_role", "selection_rationale"],
)
def test_story_chapter_rejects_a_missing_required_text_field(field: str) -> None:
    with pytest.raises(ValueError, match="identifiers and text"):
        _chapter(**{field: ""})


def test_story_chapter_rejects_an_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_time"):
        _chapter(end_time=_T0 - timedelta(seconds=1))


def test_story_chapter_rejects_a_non_positive_target_duration() -> None:
    with pytest.raises(ValueError, match="target_duration_s"):
        _chapter(target_duration_s=0.0)


def test_story_chapter_to_dict_writes_zulu_for_both_times() -> None:
    data = _chapter().to_dict()
    assert data["start_time"] == "2026-05-01T09:00:00Z"
    assert data["end_time"] == "2026-05-01T09:05:00Z"


# ---------------------------------------------------------------------------
# StoryPlan
# ---------------------------------------------------------------------------


def _plan(**overrides: object) -> StoryPlan:
    chapter = _chapter()
    fields: dict[str, object] = {
        "title": "A day's ride",
        "target_duration_s": 400.0,
        "chapters": (chapter,),
        "selected_event_ids": ("evt_1",),
        "planning_provider": "rule_based",
    }
    fields.update(overrides)
    return StoryPlan(**fields)  # type: ignore[arg-type]


def test_story_plan_rejects_an_empty_title() -> None:
    with pytest.raises(ValueError, match="title, chapters, and provider"):
        _plan(title="")


def test_story_plan_rejects_no_chapters() -> None:
    with pytest.raises(ValueError, match="title, chapters, and provider"):
        _plan(chapters=(), selected_event_ids=())


def test_story_plan_rejects_an_empty_provider() -> None:
    with pytest.raises(ValueError, match="title, chapters, and provider"):
        _plan(planning_provider="")


@pytest.mark.parametrize("duration", [299.9, 600.1])
def test_story_plan_rejects_a_duration_outside_the_five_to_ten_minute_band(
    duration: float,
) -> None:
    with pytest.raises(ValueError, match="target_duration_s"):
        _plan(target_duration_s=duration)


@pytest.mark.parametrize("duration", [300.0, 600.0])
def test_story_plan_accepts_its_own_duration_boundary(duration: float) -> None:
    plan = _plan(target_duration_s=duration)
    assert plan.target_duration_s == duration


def test_story_plan_rejects_a_chapter_count_mismatched_with_selected_events() -> None:
    with pytest.raises(ValueError, match="one selected event"):
        _plan(selected_event_ids=("evt_1", "evt_2"))


def test_story_plan_to_dict_nests_chapter_dicts() -> None:
    data = _plan().to_dict()
    assert data["selected_event_ids"] == ["evt_1"]
    assert isinstance(data["chapters"], list)
    assert data["chapters"][0]["chapter_id"] == "ch_1"


# ---------------------------------------------------------------------------
# VideoQuery
# ---------------------------------------------------------------------------


def test_video_query_rejects_a_missing_asset_name_hint() -> None:
    with pytest.raises(ValueError, match="asset_name_hint"):
        VideoQuery("")


def test_video_query_rejects_a_negative_start_offset() -> None:
    with pytest.raises(ValueError, match="clip offsets"):
        VideoQuery("fixture.mp4", clip_start_offset_s=-1.0, clip_end_offset_s=0.0)


def test_video_query_rejects_an_end_before_start_offset() -> None:
    with pytest.raises(ValueError, match="clip offsets"):
        VideoQuery("fixture.mp4", clip_start_offset_s=5.0, clip_end_offset_s=4.9)


def test_video_query_defaults_both_offsets_to_zero() -> None:
    query = VideoQuery("fixture.mp4")
    assert query.clip_start_offset_s == 0.0
    assert query.clip_end_offset_s == 0.0


# ---------------------------------------------------------------------------
# GpsEvent
# ---------------------------------------------------------------------------


def _event(**overrides: object) -> GpsEvent:
    fields: dict[str, object] = {
        "event_id": "evt_1",
        "event_type": "scenery_change",
        "start_time": _T0,
        "end_time": _T0 + timedelta(minutes=1),
        "location": Location(0.0, 0.0),
        "importance_hint": 0.5,
        "evidence": (),
        "video_query": VideoQuery("fixture.mp4", 0, 1),
    }
    fields.update(overrides)
    return GpsEvent(**fields)  # type: ignore[arg-type]


def test_gps_event_coerces_a_plain_dict_video_query() -> None:
    event = _event(video_query={"asset_name_hint": "fixture.mp4"})
    assert isinstance(event.video_query, VideoQuery)
    assert event.video_query.asset_name_hint == "fixture.mp4"


@pytest.mark.parametrize("field", ["event_id", "event_type"])
def test_gps_event_rejects_a_missing_identifier(field: str) -> None:
    with pytest.raises(ValueError, match="event_id and event_type"):
        _event(**{field: ""})


def test_gps_event_rejects_a_naive_start_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _event(start_time=datetime(2026, 5, 1, 9, 0, 0))


def test_gps_event_rejects_an_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_time"):
        _event(end_time=_T0 - timedelta(seconds=1))


@pytest.mark.parametrize("importance", [0.0, 1.0])
def test_gps_event_accepts_its_own_score_boundary(importance: float) -> None:
    event = _event(importance_hint=importance)
    assert event.importance_hint == importance


# ---------------------------------------------------------------------------
# MediaAsset
# ---------------------------------------------------------------------------


def _asset(**overrides: object) -> MediaAsset:
    fields: dict[str, object] = {
        "asset_id": "asset_1",
        "provider": "local",
        "name": "clip.mp4",
        "mime_type": "video/mp4",
        "duration_s": 12.0,
        "source_uri": "file:///clip.mp4",
    }
    fields.update(overrides)
    return MediaAsset(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["asset_id", "provider", "name", "mime_type", "source_uri"])
def test_media_asset_rejects_a_missing_identifier(field: str) -> None:
    with pytest.raises(ValueError, match="identifiers are required"):
        _asset(**{field: ""})


def test_media_asset_rejects_a_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="duration_s"):
        _asset(duration_s=0.0)


def test_media_asset_defaults_to_found() -> None:
    assert _asset().retrieval_status is RetrievalStatus.FOUND


def test_media_asset_accepts_not_found() -> None:
    asset = _asset(retrieval_status=RetrievalStatus.NOT_FOUND)
    assert asset.retrieval_status is RetrievalStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# VideoAnalysis
# ---------------------------------------------------------------------------


def _analysis(**overrides: object) -> VideoAnalysis:
    fields: dict[str, object] = {
        "asset_id": "asset_1",
        "start_offset_s": 0.0,
        "end_offset_s": 6.0,
        "visual_description": "riding along a coastal road",
        "road_type": "coastal",
        "scenery_tags": ("ocean",),
        "weather_visible": "clear",
        "visual_interest_score": 0.7,
        "story_relevance_score": 0.6,
        "confidence": 0.9,
        "analysis_provider": "gemini-2.5-flash",
    }
    fields.update(overrides)
    return VideoAnalysis(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["asset_id", "visual_description", "analysis_provider"])
def test_video_analysis_rejects_a_missing_identifier(field: str) -> None:
    with pytest.raises(ValueError, match="identifiers and description"):
        _analysis(**{field: ""})


def test_video_analysis_rejects_an_end_offset_before_start() -> None:
    with pytest.raises(ValueError, match="analysis offsets"):
        _analysis(start_offset_s=6.0, end_offset_s=5.9)


@pytest.mark.parametrize(
    "field",
    ["visual_interest_score", "story_relevance_score", "confidence"],
)
def test_video_analysis_rejects_any_out_of_range_score(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _analysis(**{field: 1.5})


# ---------------------------------------------------------------------------
# StoryDecision
# ---------------------------------------------------------------------------


def _decision(**overrides: object) -> StoryDecision:
    fields: dict[str, object] = {
        "event_id": "evt_1",
        "needs_video_evidence": False,
        "reason": "clear from GPS alone",
        "asset_name_hint": None,
        "decision_status": DecisionStatus.ACCEPTED,
        "updated_story_role": "opening",
    }
    fields.update(overrides)
    return StoryDecision(**fields)  # type: ignore[arg-type]


def test_story_decision_rejects_a_missing_reason() -> None:
    with pytest.raises(ValueError, match="event_id and reason"):
        _decision(reason="")


def test_story_decision_requires_an_asset_hint_when_evidence_is_needed() -> None:
    with pytest.raises(ValueError, match="asset_name_hint is required"):
        _decision(
            needs_video_evidence=True,
            asset_name_hint=None,
            decision_status=DecisionStatus.AWAITING_VIDEO_EVIDENCE,
            updated_story_role=None,
        )


def test_story_decision_requires_a_role_once_accepted() -> None:
    with pytest.raises(ValueError, match="accepted decisions require"):
        _decision(decision_status=DecisionStatus.ACCEPTED, updated_story_role=None)


def test_story_decision_allows_no_role_when_not_accepted() -> None:
    decision = _decision(
        decision_status=DecisionStatus.REJECTED,
        updated_story_role=None,
    )
    assert decision.updated_story_role is None


def test_story_decision_to_dict_writes_the_status_as_its_plain_string_value() -> None:
    data = _decision().to_dict()
    assert data["decision_status"] == "accepted"
