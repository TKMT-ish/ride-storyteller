from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import GpsEvent, Location, VideoQuery
from app.video.apple_vision import VisionClassification, VisionImageAnalysis
from app.video.gpmf_metrics import GpmfWindowSummary
from app.video.highlight_discovery import WindowFeatures
from app.video.highlight_quality import (
    HighlightWindowEvidence,
    InterestLane,
    QualitySelection,
    QualitySelectionMethod,
    ScoredHighlightWindow,
)
from app.video.highlight_review import HighlightReviewResult, highlight_review_candidate_id
from app.video.highlight_story_bridge import (
    HIGHLIGHT_EVENT_TYPE,
    HighlightBridgeCandidate,
    HighlightStoryBridgeError,
    build_highlight_gps_event,
    build_highlight_gps_events,
    export_highlight_bridge_candidates,
    highlight_bridge_candidate_from_selection,
    load_highlight_bridge_candidates,
    overlaps_existing_event,
    write_highlight_bridge_candidates,
)

_WINDOW_START = datetime(2026, 8, 30, 9, 0, 0, tzinfo=UTC)


def _selection(
    method: QualitySelectionMethod,
    rank: int,
    *,
    asset_id: str = "asset-a",
    start_time: datetime = _WINDOW_START,
    duration_s: float = 12.0,
    latitude: float | None = 35.0,
    longitude: float | None = 139.0,
    interest_lanes: tuple[InterestLane, ...] = (InterestLane.STRONG_TURN,),
    score: float = 0.8,
) -> QualitySelection:
    window = WindowFeatures(
        asset_id=asset_id,
        start_offset_s=rank * 12.0,
        duration_s=duration_s,
        timeline_s=start_time.timestamp(),
        mean_speed_mps=12.0,
        minimum_speed_mps=8.0,
        speed_p10_mps=9.0,
        center_speed_mps=10.0,
        moving_ratio=1.0,
        heading_change_degrees=24.0,
        center_heading_change_degrees=14.0,
        accumulated_heading_change_degrees=34.0,
        path_efficiency=0.95,
        speed_std_mps=2.0,
        speed_range_mps=4.0,
        elevation_change_m=2.0,
        elevation_range_m=4.0,
        motion_mean=10.0,
        motion_std=2.0,
        scene_change_mean=12.0,
        scene_change_peak_ratio=0.2,
        blur_mean=3.0,
        luma_mean=120.0,
        dynamic_range_mean=180.0,
        saturation_mean=25.0,
        entropy_mean=0.9,
        latitude=latitude,
        longitude=longitude,
    )
    frames = tuple(
        VisionImageAnalysis(
            index=rank * 10 + index,
            aesthetic_score=0.5,
            is_utility=False,
            classifications=(VisionClassification("road", 0.9),),
        )
        for index in range(3)
    )
    evidence = HighlightWindowEvidence(
        window=window,
        gpmf=GpmfWindowSummary(
            gyro_sustained_rad_s=0.2,
            center_gyro_sustained_rad_s=0.2,
            gyro_jitter_rad_s=0.1,
            gyro_peak_rad_s=0.4,
            acceleration_jitter_mps2=1.0,
            iso_mean=100.0,
            shutter_mean_s=0.001,
            luma_mean=120.0,
            uniformity_mean=0.2,
            natural_scene_probability=0.7,
            built_scene_probability=0.3,
            scene_confidence=0.6,
            hue_weight_mean=0.5,
            coverage_ratio=1.0,
        ),
        frames=frames,
        feature_index=frames[1].index,
    )
    return QualitySelection(
        method=method,
        rank=rank,
        scored=ScoredHighlightWindow(
            evidence=evidence,
            interest_lanes=interest_lanes,
            quality_score=score,
            dynamics_score=score,
            scenic_score=score,
            balanced_score=score,
        ),
        relevance_score=score,
        diversity_gain=0.5,
    )


def _candidate(
    *,
    candidate_id: str = "highlight-abc123",
    method: QualitySelectionMethod = QualitySelectionMethod.QUALITY_FIRST,
    rank: int = 1,
    start_time: datetime = _WINDOW_START,
    duration_s: float = 12.0,
    latitude: float = 35.0,
    longitude: float = 139.0,
    interest_lanes: tuple[InterestLane, ...] = (InterestLane.STRONG_TURN,),
    score: float = 0.8,
) -> HighlightBridgeCandidate:
    return HighlightBridgeCandidate(
        candidate_id=candidate_id,
        method=method,
        rank=rank,
        start_time=start_time,
        duration_s=duration_s,
        location=Location(latitude, longitude),
        interest_lanes=interest_lanes,
        score=score,
    )


def _gps_event(
    event_id: str, start_time: datetime, end_time: datetime, event_type: str = "stop"
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=start_time,
        end_time=end_time,
        location=Location(35.1, 139.1),
        importance_hint=0.5,
        evidence=("gps_stop",),
        video_query=VideoQuery(
            asset_name_hint="ride.mp4", clip_start_offset_s=0.0, clip_end_offset_s=10.0
        ),
    )


# ---------------------------------------------------------------------------
# Projection: QualitySelection -> HighlightBridgeCandidate
# ---------------------------------------------------------------------------


def test_highlight_bridge_candidate_from_selection_projects_only_the_needed_fields() -> None:
    selection = _selection(QualitySelectionMethod.QUALITY_FIRST, 1)

    candidate = highlight_bridge_candidate_from_selection(selection)

    assert candidate.candidate_id == highlight_review_candidate_id(selection)
    assert candidate.start_time == _WINDOW_START
    assert candidate.duration_s == 12.0
    assert candidate.location.latitude == pytest.approx(35.0)
    assert candidate.location.longitude == pytest.approx(139.0)
    assert candidate.interest_lanes == (InterestLane.STRONG_TURN,)
    assert candidate.score == pytest.approx(0.8)


def test_highlight_bridge_candidate_from_selection_rejects_missing_location() -> None:
    selection = _selection(QualitySelectionMethod.QUALITY_FIRST, 1, latitude=None, longitude=None)

    with pytest.raises(HighlightStoryBridgeError, match="no recorded GPS location"):
        highlight_bridge_candidate_from_selection(selection)


def test_export_highlight_bridge_candidates_only_includes_approved() -> None:
    approved = _selection(QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="asset-a")
    rejected = _selection(QualitySelectionMethod.RIDE_DYNAMICS, 1, asset_id="asset-b")
    selections = {
        QualitySelectionMethod.QUALITY_FIRST: (approved,),
        QualitySelectionMethod.RIDE_DYNAMICS: (rejected,),
    }
    review_result = HighlightReviewResult(
        approved_candidate_ids=(highlight_review_candidate_id(approved),),
        awaiting_candidate_ids=(),
        rejected_candidate_ids=(highlight_review_candidate_id(rejected),),
        reason_counts={},
    )

    candidate_set = export_highlight_bridge_candidates(selections, review_result)

    assert [candidate.candidate_id for candidate in candidate_set.candidates] == [
        highlight_review_candidate_id(approved)
    ]


def test_export_highlight_bridge_candidates_skips_missing_location_without_failing() -> None:
    approved_with_location = _selection(
        QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="asset-a"
    )
    approved_without_location = _selection(
        QualitySelectionMethod.RIDE_DYNAMICS,
        1,
        asset_id="asset-b",
        latitude=None,
        longitude=None,
    )
    selections = {
        QualitySelectionMethod.QUALITY_FIRST: (approved_with_location,),
        QualitySelectionMethod.RIDE_DYNAMICS: (approved_without_location,),
    }
    review_result = HighlightReviewResult(
        approved_candidate_ids=(
            highlight_review_candidate_id(approved_with_location),
            highlight_review_candidate_id(approved_without_location),
        ),
        awaiting_candidate_ids=(),
        rejected_candidate_ids=(),
        reason_counts={},
    )

    candidate_set = export_highlight_bridge_candidates(selections, review_result)

    assert len(candidate_set.candidates) == 1
    assert candidate_set.candidates[0].candidate_id == highlight_review_candidate_id(
        approved_with_location
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_highlight_bridge_candidates_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "highlight-bridge-candidates.json"
    selection = _selection(QualitySelectionMethod.QUALITY_FIRST, 1)
    candidate_set = export_highlight_bridge_candidates(
        {QualitySelectionMethod.QUALITY_FIRST: (selection,)},
        HighlightReviewResult(
            approved_candidate_ids=(highlight_review_candidate_id(selection),),
            awaiting_candidate_ids=(),
            rejected_candidate_ids=(),
            reason_counts={},
        ),
    )

    write_highlight_bridge_candidates(path, candidate_set)
    reloaded = load_highlight_bridge_candidates(path)

    assert reloaded == candidate_set


def test_highlight_bridge_candidates_payload_excludes_asset_identity(tmp_path: Path) -> None:
    path = tmp_path / "highlight-bridge-candidates.json"
    selection = _selection(QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="asset-secret")
    candidate_set = export_highlight_bridge_candidates(
        {QualitySelectionMethod.QUALITY_FIRST: (selection,)},
        HighlightReviewResult(
            approved_candidate_ids=(highlight_review_candidate_id(selection),),
            awaiting_candidate_ids=(),
            rejected_candidate_ids=(),
            reason_counts={},
        ),
    )

    write_highlight_bridge_candidates(path, candidate_set)

    payload = path.read_text(encoding="utf-8")
    assert "asset-secret" not in payload
    assert "road" not in payload  # no Vision classification label
    assert "gyro" not in payload  # no raw GPMF metric


def test_write_highlight_bridge_candidates_overwrite_flag(tmp_path: Path) -> None:
    path = tmp_path / "highlight-bridge-candidates.json"
    from app.video.highlight_story_bridge import HighlightBridgeCandidateSet

    empty = HighlightBridgeCandidateSet(())
    write_highlight_bridge_candidates(path, empty)

    with pytest.raises(FileExistsError, match="already exist"):
        write_highlight_bridge_candidates(path, empty, overwrite=False)

    assert write_highlight_bridge_candidates(path, empty, overwrite=True) == path


def test_load_highlight_bridge_candidates_rejects_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "highlight-bridge-candidates.json"
    path.write_text('{"schema_version": "other"}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        load_highlight_bridge_candidates(path)


# ---------------------------------------------------------------------------
# GpsEvent synthesis
# ---------------------------------------------------------------------------


def test_build_highlight_gps_event_from_candidate() -> None:
    candidate = _candidate()

    event = build_highlight_gps_event(candidate)

    assert event.event_type == HIGHLIGHT_EVENT_TYPE
    assert event.start_time == _WINDOW_START
    assert event.end_time == _WINDOW_START + timedelta(seconds=12.0)
    assert event.location.latitude == pytest.approx(35.0)
    assert event.location.longitude == pytest.approx(139.0)
    assert event.evidence == ("strong_turn",)
    assert event.importance_hint == pytest.approx(0.8)


def test_build_highlight_gps_event_combines_both_lanes_in_evidence() -> None:
    candidate = _candidate(interest_lanes=(InterestLane.STRONG_TURN, InterestLane.VISUAL_EVENT))

    event = build_highlight_gps_event(candidate)

    assert event.evidence == ("strong_turn", "visual_event")


def test_overlaps_existing_event_detects_time_intersection() -> None:
    candidate = _candidate()
    overlapping = _gps_event(
        "evt_stop", _WINDOW_START + timedelta(seconds=5), _WINDOW_START + timedelta(seconds=20)
    )
    distant = _gps_event(
        "evt_far",
        _WINDOW_START + timedelta(hours=2),
        _WINDOW_START + timedelta(hours=2, seconds=30),
    )

    assert overlaps_existing_event(candidate, (overlapping,)) is True
    assert overlaps_existing_event(candidate, (distant,)) is False
    assert overlaps_existing_event(candidate, ()) is False


def test_build_highlight_gps_events_skips_overlapping_candidates() -> None:
    clear = _candidate(candidate_id="highlight-clear")
    overlapping = _candidate(
        candidate_id="highlight-overlap", start_time=_WINDOW_START + timedelta(hours=1)
    )
    existing = (
        _gps_event(
            "evt_stop",
            _WINDOW_START + timedelta(hours=1),
            _WINDOW_START + timedelta(hours=1, seconds=30),
        ),
    )

    events = build_highlight_gps_events((clear, overlapping), existing)

    assert len(events) == 1
    assert events[0].start_time == _WINDOW_START


def test_build_highlight_gps_events_deduplicates_the_same_window_across_methods() -> None:
    same_window_a = _candidate(
        candidate_id="highlight-a", method=QualitySelectionMethod.QUALITY_FIRST
    )
    same_window_b = _candidate(
        candidate_id="highlight-b", method=QualitySelectionMethod.RIDE_DYNAMICS
    )

    events = build_highlight_gps_events((same_window_a, same_window_b), ())

    assert len(events) == 1


def test_build_highlight_gps_events_returns_chronological_order() -> None:
    later = _candidate(
        candidate_id="highlight-later", start_time=_WINDOW_START + timedelta(hours=2)
    )
    earlier = _candidate(candidate_id="highlight-earlier", start_time=_WINDOW_START)

    events = build_highlight_gps_events((later, earlier), ())

    assert [event.start_time for event in events] == [
        _WINDOW_START,
        _WINDOW_START + timedelta(hours=2),
    ]
