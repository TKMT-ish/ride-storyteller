import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import app.video.highlight_story_bridge as highlight_story_bridge_module
from app.contracts import GpsEvent, Location, VideoQuery
from app.video.apple_vision import VisionClassification, VisionImageAnalysis
from app.video.catalog import (
    ResolvedCandidateClip,
    VideoCatalog,
    VideoCatalogEntry,
    VideoMatchStatus,
)
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
    HighlightReinforcementConflict,
    HighlightReinforcementConflictSet,
    HighlightReinforcementSelection,
    HighlightReinforcementSelectionSet,
    HighlightStoryBridgeError,
    build_highlight_gps_event,
    build_highlight_gps_events,
    export_highlight_bridge_candidates,
    find_highlight_reinforcement_conflicts,
    highlight_bridge_candidate_from_selection,
    load_highlight_bridge_candidates,
    load_highlight_reinforcement_conflicts,
    load_highlight_reinforcement_selections,
    overlaps_existing_event,
    reinforce_resolved_clips_with_highlights,
    write_highlight_bridge_candidates,
    write_highlight_reinforcement_conflicts,
    write_highlight_reinforcement_selections,
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
    approved_with_location = _selection(QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="asset-a")
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


# ---------------------------------------------------------------------------
# reinforce_resolved_clips_with_highlights
#
# Real-media testing on 2026-09-02 found that on an actual ride every
# highlight candidate overlapped an existing GPS event, so the "add a new
# event" path alone added nothing (docs/highlight-story-bridge-design-ja.md
# §7-5). These tests cover the reinforcement path added to make an
# overlapping candidate useful instead of discarded.
# ---------------------------------------------------------------------------

_ASSET_ID = "asset-catalog-1"


def _catalog_entry(
    asset_id: str = _ASSET_ID,
    *,
    file_name: str = "source.mp4",
    recorded_start_time: datetime = _WINDOW_START,
    duration_s: float = 600.0,
) -> VideoCatalogEntry:
    return VideoCatalogEntry(
        asset_id=asset_id,
        file_name=file_name,
        recorded_start_time=recorded_start_time,
        duration_s=duration_s,
    )


def _catalog(*entries: VideoCatalogEntry, video_to_gps_offset_s: float = 0.0) -> VideoCatalog:
    return VideoCatalog(entries=entries, video_to_gps_offset_s=video_to_gps_offset_s)


def _resolved_clip(
    *,
    chapter_id: str = "chapter_01",
    event_id: str = "evt_001",
    status: VideoMatchStatus = VideoMatchStatus.MATCHED,
    asset_id: str | None = _ASSET_ID,
    file_name: str | None = "source.mp4",
    start_offset_s: float | None = 30.0,
    end_offset_s: float | None = 60.0,
    reason: str = "補正後のGPS時刻が動画の記録区間に含まれます。",
) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        status=status,
        asset_id=asset_id,
        file_name=file_name,
        start_offset_s=start_offset_s,
        end_offset_s=end_offset_s,
        reason=reason,
    )


def test_reinforce_narrows_when_candidate_is_a_tighter_same_asset_subset() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        candidate_id="highlight-tighter",
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (candidate,), catalog)

    assert len(reinforced) == 1
    result = reinforced[0]
    assert result.asset_id == clip.asset_id
    assert result.status is VideoMatchStatus.MATCHED
    assert result.start_offset_s == pytest.approx(40.0)
    assert result.end_offset_s == pytest.approx(50.0)
    assert result.reason != clip.reason


def test_reinforce_leaves_unmatched_clip_untouched() -> None:
    clip = _resolved_clip(
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="補正後のGPS時刻を含む素材カタログ項目がありません。",
    )
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(start_time=_WINDOW_START + timedelta(seconds=40), duration_s=10.0)

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (candidate,), catalog)

    assert reinforced == (clip,)


def test_reinforce_leaves_clip_unchanged_when_no_candidate_overlaps() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    distant_candidate = _candidate(
        start_time=_WINDOW_START + timedelta(seconds=400), duration_s=10.0
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (distant_candidate,), catalog)

    assert reinforced == (clip,)


def test_reinforce_leaves_clip_unchanged_when_same_method_candidates_tie_on_rank() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    first = _candidate(
        candidate_id="highlight-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=35),
        duration_s=5.0,
    )
    second = _candidate(
        candidate_id="highlight-second",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=5.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (first, second), catalog)

    assert reinforced == (clip,)


def test_reinforce_narrows_using_the_uniquely_lowest_rank_within_one_method() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    best = _candidate(
        candidate_id="highlight-best",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    runner_up = _candidate(
        candidate_id="highlight-runner-up",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=2,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (best, runner_up), catalog)

    assert len(reinforced) == 1
    result = reinforced[0]
    assert result.start_offset_s == pytest.approx(40.0)
    assert result.end_offset_s == pytest.approx(50.0)
    assert result.reason != clip.reason


def test_reinforce_leaves_clip_unchanged_when_candidates_are_from_different_methods() -> None:
    """Score/rank are not comparable across methods, so a mix is ambiguous
    even when one candidate's rank number happens to be numerically lower."""
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    quality_first = _candidate(
        candidate_id="highlight-quality-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    ride_dynamics = _candidate(
        candidate_id="highlight-ride-dynamics",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=2,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (quality_first, ride_dynamics), catalog
    )

    assert reinforced == (clip,)


def test_reinforce_ignores_an_asset_mismatched_candidate_and_still_narrows() -> None:
    """An invalid (cross-asset) candidate mixed in with a real overlap does
    not itself force ambiguity: it is dropped, and the one remaining valid
    candidate is used."""
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    valid = _candidate(
        candidate_id="highlight-valid",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    cross_asset = _candidate(
        candidate_id="highlight-cross-asset",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=1,
        start_time=_WINDOW_START - timedelta(seconds=5),
        duration_s=10.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (valid, cross_asset), catalog)

    assert len(reinforced) == 1
    result = reinforced[0]
    assert result.start_offset_s == pytest.approx(40.0)
    assert result.end_offset_s == pytest.approx(50.0)


def test_reinforce_rejects_candidate_extending_outside_the_asset_bounds() -> None:
    """A candidate whose window is not fully inside the resolved asset's span
    is treated as an asset-identity mismatch, even though it overlaps the
    clip in absolute time (e.g. a coincidental cross-recording overlap)."""
    clip = _resolved_clip(start_offset_s=0.0, end_offset_s=10.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        start_time=_WINDOW_START - timedelta(seconds=5),
        duration_s=10.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (candidate,), catalog)

    assert reinforced == (clip,)


def test_reinforce_leaves_clip_unchanged_when_candidate_is_not_narrower() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    wider_candidate = _candidate(
        start_time=_WINDOW_START + timedelta(seconds=25),
        duration_s=40.0,
    )

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (wider_candidate,), catalog)

    assert reinforced == (clip,)


def test_reinforce_leaves_clip_unchanged_when_asset_missing_from_catalog() -> None:
    clip = _resolved_clip(asset_id="asset-not-in-catalog", start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(start_time=_WINDOW_START + timedelta(seconds=40), duration_s=10.0)

    reinforced = reinforce_resolved_clips_with_highlights((clip,), (candidate,), catalog)

    assert reinforced == (clip,)


def test_reinforce_only_touches_the_clip_the_candidate_overlaps() -> None:
    reinforceable = _resolved_clip(event_id="evt_001", start_offset_s=30.0, end_offset_s=60.0)
    untouched = _resolved_clip(
        event_id="evt_002",
        chapter_id="chapter_02",
        start_offset_s=200.0,
        end_offset_s=230.0,
    )
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(start_time=_WINDOW_START + timedelta(seconds=40), duration_s=10.0)

    reinforced = reinforce_resolved_clips_with_highlights(
        (reinforceable, untouched), (candidate,), catalog
    )

    assert reinforced[1] == untouched
    assert reinforced[0].start_offset_s == pytest.approx(40.0)
    assert reinforced[0].end_offset_s == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# HighlightReinforcementSelection / HighlightReinforcementSelectionSet
# ---------------------------------------------------------------------------


def test_reinforcement_selection_requires_event_id_and_candidate_id() -> None:
    with pytest.raises(ValueError, match="event_id and candidate_id"):
        HighlightReinforcementSelection(event_id="", candidate_id="highlight-abc")
    with pytest.raises(ValueError, match="event_id and candidate_id"):
        HighlightReinforcementSelection(event_id="evt_001", candidate_id="")


def test_reinforcement_selection_set_rejects_duplicate_event_id() -> None:
    with pytest.raises(ValueError, match="unique event_id and candidate_id"):
        HighlightReinforcementSelectionSet(
            (
                HighlightReinforcementSelection("evt_001", "highlight-a"),
                HighlightReinforcementSelection("evt_001", "highlight-b"),
            )
        )


def test_reinforcement_selection_set_rejects_duplicate_candidate_id() -> None:
    with pytest.raises(ValueError, match="unique event_id and candidate_id"):
        HighlightReinforcementSelectionSet(
            (
                HighlightReinforcementSelection("evt_001", "highlight-a"),
                HighlightReinforcementSelection("evt_002", "highlight-a"),
            )
        )


def test_reinforcement_selection_set_candidate_id_for_looks_up_by_event() -> None:
    selection_set = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection("evt_001", "highlight-a"),)
    )

    assert selection_set.candidate_id_for("evt_001") == "highlight-a"
    assert selection_set.candidate_id_for("evt_999") is None


# ---------------------------------------------------------------------------
# Persistence: load/write_highlight_reinforcement_selections
# ---------------------------------------------------------------------------


def test_highlight_reinforcement_selections_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    selection_set = HighlightReinforcementSelectionSet(
        (
            HighlightReinforcementSelection("evt_001", "highlight-a"),
            HighlightReinforcementSelection("evt_002", "highlight-b"),
        )
    )

    write_highlight_reinforcement_selections(path, selection_set)
    reloaded = load_highlight_reinforcement_selections(path)

    assert reloaded == selection_set


def test_write_highlight_reinforcement_selections_defaults_to_no_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    selection_set = HighlightReinforcementSelectionSet(())
    write_highlight_reinforcement_selections(path, selection_set)

    with pytest.raises(FileExistsError, match="already exist"):
        write_highlight_reinforcement_selections(path, selection_set)

    assert write_highlight_reinforcement_selections(path, selection_set, overwrite=True) == path


def test_write_highlight_reinforcement_selections_rejects_symlink_target(
    tmp_path: Path,
) -> None:
    real_target = tmp_path / "real.json"
    real_target.write_text("{}", encoding="utf-8")
    link_path = tmp_path / "link.json"
    link_path.symlink_to(real_target)

    with pytest.raises(ValueError, match="must not be a symlink"):
        write_highlight_reinforcement_selections(
            link_path, HighlightReinforcementSelectionSet(()), overwrite=True
        )


def test_highlight_reinforcement_selections_atomic_write_preserves_existing_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    original = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection("evt_001", "highlight-a"),)
    )
    write_highlight_reinforcement_selections(path, original)
    original_payload = path.read_text(encoding="utf-8")
    replacement = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection("evt_001", "highlight-b"),)
    )

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(highlight_story_bridge_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_highlight_reinforcement_selections(path, replacement, overwrite=True)

    assert path.read_text(encoding="utf-8") == original_payload
    assert not list(tmp_path.glob(".highlight-reinforcement-selections.json.*.tmp"))


def test_load_highlight_reinforcement_selections_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        load_highlight_reinforcement_selections(tmp_path / "missing.json")


def test_load_highlight_reinforcement_selections_rejects_symlink(tmp_path: Path) -> None:
    real_target = tmp_path / "real.json"
    write_highlight_reinforcement_selections(real_target, HighlightReinforcementSelectionSet(()))
    link_path = tmp_path / "link.json"
    link_path.symlink_to(real_target)

    with pytest.raises(ValueError, match="unavailable"):
        load_highlight_reinforcement_selections(link_path)


def test_load_highlight_reinforcement_selections_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        load_highlight_reinforcement_selections(path)


def test_load_highlight_reinforcement_selections_rejects_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text(json.dumps({"schema_version": "other", "selections": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        load_highlight_reinforcement_selections(path)


def test_load_highlight_reinforcement_selections_rejects_unknown_top_level_field(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-selection-v1",
                "selections": [],
                "note": "unexpected",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_selections(path)


def test_load_highlight_reinforcement_selections_rejects_unknown_selection_field(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-selection-v1",
                "selections": [
                    {"event_id": "evt_001", "candidate_id": "highlight-a", "note": "extra"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_selections(path)


def test_load_highlight_reinforcement_selections_rejects_non_string_identifiers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-selection-v1",
                "selections": [{"event_id": "evt_001", "candidate_id": 123}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_selections(path)


def test_load_highlight_reinforcement_selections_rejects_duplicate_event_id(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-selections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-selection-v1",
                "selections": [
                    {"event_id": "evt_001", "candidate_id": "highlight-a"},
                    {"event_id": "evt_001", "candidate_id": "highlight-b"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique event_id and candidate_id"):
        load_highlight_reinforcement_selections(path)


# ---------------------------------------------------------------------------
# reinforce_resolved_clips_with_highlights(selections=...)
# ---------------------------------------------------------------------------


def test_reinforce_uses_explicit_selection_to_resolve_a_method_mismatch_ambiguity() -> None:
    """Two candidates from different methods are ambiguous automatically
    (see test_reinforce_leaves_clip_unchanged_when_candidates_are_from_different_methods);
    an explicit, valid selection resolves it deterministically."""
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    quality_first = _candidate(
        candidate_id="highlight-quality-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    ride_dynamics = _candidate(
        candidate_id="highlight-ride-dynamics",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=2,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, "highlight-ride-dynamics"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (quality_first, ride_dynamics), catalog, selections=selections
    )

    assert len(reinforced) == 1
    result = reinforced[0]
    assert result.start_offset_s == pytest.approx(45.0)
    assert result.end_offset_s == pytest.approx(55.0)


def test_reinforce_uses_explicit_selection_to_resolve_a_tied_rank_ambiguity() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    first = _candidate(
        candidate_id="highlight-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=35),
        duration_s=5.0,
    )
    second = _candidate(
        candidate_id="highlight-second",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=5.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, "highlight-second"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (first, second), catalog, selections=selections
    )

    assert len(reinforced) == 1
    result = reinforced[0]
    assert result.start_offset_s == pytest.approx(45.0)
    assert result.end_offset_s == pytest.approx(50.0)


def test_reinforce_falls_back_to_automatic_when_no_selection_for_this_event() -> None:
    clip = _resolved_clip(event_id="evt_001", start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        candidate_id="highlight-tighter",
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection("evt_999", "highlight-tighter"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (candidate,), catalog, selections=selections
    )

    assert len(reinforced) == 1
    assert reinforced[0].start_offset_s == pytest.approx(40.0)
    assert reinforced[0].end_offset_s == pytest.approx(50.0)


def test_reinforce_ignores_selection_referencing_an_unknown_candidate_id() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        candidate_id="highlight-real",
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, "highlight-does-not-exist"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (candidate,), catalog, selections=selections
    )

    assert reinforced == (clip,)


def test_reinforce_ignores_selection_whose_candidate_is_asset_mismatched() -> None:
    clip = _resolved_clip(start_offset_s=0.0, end_offset_s=10.0)
    catalog = _catalog(_catalog_entry())
    cross_asset = _candidate(
        candidate_id="highlight-cross-asset",
        start_time=_WINDOW_START - timedelta(seconds=5),
        duration_s=10.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, "highlight-cross-asset"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (cross_asset,), catalog, selections=selections
    )

    assert reinforced == (clip,)


def test_reinforce_ignores_selection_whose_candidate_does_not_narrow() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    wider_candidate = _candidate(
        candidate_id="highlight-wider",
        start_time=_WINDOW_START + timedelta(seconds=25),
        duration_s=40.0,
    )
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, "highlight-wider"),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (wider_candidate,), catalog, selections=selections
    )

    assert reinforced == (clip,)


def test_reinforce_ignores_selection_for_an_unmatched_clip() -> None:
    clip = _resolved_clip(
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="補正後のGPS時刻を含む素材カタログ項目がありません。",
    )
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(start_time=_WINDOW_START + timedelta(seconds=40), duration_s=10.0)
    selections = HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(clip.event_id, candidate.candidate_id),)
    )

    reinforced = reinforce_resolved_clips_with_highlights(
        (clip,), (candidate,), catalog, selections=selections
    )

    assert reinforced == (clip,)


def test_reinforce_with_none_selections_matches_omitting_the_argument() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )

    with_default = reinforce_resolved_clips_with_highlights((clip,), (candidate,), catalog)
    with_explicit_none = reinforce_resolved_clips_with_highlights(
        (clip,), (candidate,), catalog, selections=None
    )

    assert with_default == with_explicit_none


# ---------------------------------------------------------------------------
# find_highlight_reinforcement_conflicts
# ---------------------------------------------------------------------------


def test_reinforcement_conflict_requires_identifiers_and_positive_rank() -> None:
    with pytest.raises(ValueError, match="event_id and candidate_id"):
        HighlightReinforcementConflict("", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1)
    with pytest.raises(ValueError, match="event_id and candidate_id"):
        HighlightReinforcementConflict("evt_001", "", QualitySelectionMethod.QUALITY_FIRST, 1)
    with pytest.raises(ValueError, match="rank must be positive"):
        HighlightReinforcementConflict(
            "evt_001", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 0
        )


def test_reinforcement_conflict_set_rejects_repeated_event_candidate_pairing() -> None:
    conflict = HighlightReinforcementConflict(
        "evt_001", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1
    )
    with pytest.raises(ValueError, match="not repeat an event/candidate pairing"):
        HighlightReinforcementConflictSet((conflict, conflict))


def test_reinforcement_conflict_set_rejects_the_same_candidate_under_two_events() -> None:
    with pytest.raises(ValueError, match="not list the same candidate twice"):
        HighlightReinforcementConflictSet(
            (
                HighlightReinforcementConflict(
                    "evt_001", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1
                ),
                HighlightReinforcementConflict(
                    "evt_002", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1
                ),
            )
        )


def test_find_conflicts_lists_a_method_mismatch() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    quality_first = _candidate(
        candidate_id="highlight-quality-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    ride_dynamics = _candidate(
        candidate_id="highlight-ride-dynamics",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=2,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )

    conflicts = find_highlight_reinforcement_conflicts(
        (clip,), (quality_first, ride_dynamics), catalog
    )

    assert conflicts == HighlightReinforcementConflictSet(
        (
            HighlightReinforcementConflict(
                clip.event_id, "highlight-quality-first", QualitySelectionMethod.QUALITY_FIRST, 1
            ),
            HighlightReinforcementConflict(
                clip.event_id, "highlight-ride-dynamics", QualitySelectionMethod.RIDE_DYNAMICS, 2
            ),
        )
    )


def test_find_conflicts_lists_a_tied_rank_within_one_method() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    first = _candidate(
        candidate_id="highlight-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=35),
        duration_s=5.0,
    )
    second = _candidate(
        candidate_id="highlight-second",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=5.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (first, second), catalog)

    assert {conflict.candidate_id for conflict in conflicts.conflicts} == {
        "highlight-first",
        "highlight-second",
    }
    assert all(conflict.event_id == clip.event_id for conflict in conflicts.conflicts)


def test_find_conflicts_excludes_a_clip_that_already_resolves_automatically() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    best = _candidate(
        candidate_id="highlight-best",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    runner_up = _candidate(
        candidate_id="highlight-runner-up",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=2,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (best, runner_up), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_excludes_a_clip_with_a_single_valid_candidate() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    candidate = _candidate(
        candidate_id="highlight-only",
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (candidate,), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_drops_an_asset_mismatched_candidate_before_ambiguity() -> None:
    """An invalid cross-asset candidate must not, by itself, manufacture a
    conflict: once dropped, only one real candidate remains, so this clip
    resolves automatically and is not listed."""
    clip = _resolved_clip(start_offset_s=0.0, end_offset_s=10.0)
    catalog = _catalog(_catalog_entry())
    valid = _candidate(
        candidate_id="highlight-valid",
        start_time=_WINDOW_START + timedelta(seconds=2),
        duration_s=5.0,
    )
    cross_asset = _candidate(
        candidate_id="highlight-cross-asset",
        start_time=_WINDOW_START - timedelta(seconds=5),
        duration_s=10.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (valid, cross_asset), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_drops_a_non_narrowing_candidate_before_ambiguity() -> None:
    clip = _resolved_clip(start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    narrower = _candidate(
        candidate_id="highlight-narrower",
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    wider = _candidate(
        candidate_id="highlight-wider",
        start_time=_WINDOW_START + timedelta(seconds=25),
        duration_s=40.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (narrower, wider), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_ignores_an_unmatched_clip() -> None:
    clip = _resolved_clip(
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="補正後のGPS時刻を含む素材カタログ項目がありません。",
    )
    catalog = _catalog(_catalog_entry())
    first = _candidate(
        candidate_id="highlight-first",
        start_time=_WINDOW_START + timedelta(seconds=35),
        duration_s=5.0,
    )
    second = _candidate(
        candidate_id="highlight-second",
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=5.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (first, second), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_ignores_a_clip_whose_asset_is_missing_from_catalog() -> None:
    clip = _resolved_clip(asset_id="missing-asset", start_offset_s=30.0, end_offset_s=60.0)
    catalog = _catalog(_catalog_entry())
    first = _candidate(
        candidate_id="highlight-first",
        start_time=_WINDOW_START + timedelta(seconds=35),
        duration_s=5.0,
    )
    second = _candidate(
        candidate_id="highlight-second",
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=5.0,
    )

    conflicts = find_highlight_reinforcement_conflicts((clip,), (first, second), catalog)

    assert conflicts == HighlightReinforcementConflictSet(())


def test_find_conflicts_orders_deterministically_across_multiple_clips() -> None:
    early_clip = _resolved_clip(event_id="evt_a", start_offset_s=30.0, end_offset_s=60.0)
    later_entry = _catalog_entry(
        "asset-catalog-2", recorded_start_time=_WINDOW_START + timedelta(hours=1)
    )
    later_clip = _resolved_clip(
        event_id="evt_b",
        asset_id="asset-catalog-2",
        start_offset_s=30.0,
        end_offset_s=60.0,
    )
    catalog = _catalog(_catalog_entry(), later_entry)

    early_first = _candidate(
        candidate_id="highlight-a-first",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=40),
        duration_s=10.0,
    )
    early_second = _candidate(
        candidate_id="highlight-a-second",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(seconds=45),
        duration_s=10.0,
    )
    later_first = _candidate(
        candidate_id="highlight-b-first",
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        start_time=_WINDOW_START + timedelta(hours=1, seconds=40),
        duration_s=10.0,
    )
    later_second = _candidate(
        candidate_id="highlight-b-second",
        method=QualitySelectionMethod.RIDE_DYNAMICS,
        rank=2,
        start_time=_WINDOW_START + timedelta(hours=1, seconds=45),
        duration_s=10.0,
    )

    conflicts = find_highlight_reinforcement_conflicts(
        (later_clip, early_clip),
        (later_second, later_first, early_second, early_first),
        catalog,
    )

    assert [(conflict.event_id, conflict.candidate_id) for conflict in conflicts.conflicts] == [
        ("evt_a", "highlight-a-second"),
        ("evt_a", "highlight-a-first"),
        ("evt_b", "highlight-b-first"),
        ("evt_b", "highlight-b-second"),
    ]


# ---------------------------------------------------------------------------
# Persistence: load/write_highlight_reinforcement_conflicts
# ---------------------------------------------------------------------------


def test_highlight_reinforcement_conflicts_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    conflict_set = HighlightReinforcementConflictSet(
        (
            HighlightReinforcementConflict(
                "evt_001", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1
            ),
            HighlightReinforcementConflict(
                "evt_001", "highlight-b", QualitySelectionMethod.RIDE_DYNAMICS, 2
            ),
        )
    )

    write_highlight_reinforcement_conflicts(path, conflict_set)
    reloaded = load_highlight_reinforcement_conflicts(path)

    assert reloaded == conflict_set


def test_write_highlight_reinforcement_conflicts_defaults_to_no_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    conflict_set = HighlightReinforcementConflictSet(())
    write_highlight_reinforcement_conflicts(path, conflict_set)

    with pytest.raises(FileExistsError, match="already exist"):
        write_highlight_reinforcement_conflicts(path, conflict_set)

    assert write_highlight_reinforcement_conflicts(path, conflict_set, overwrite=True) == path


def test_write_highlight_reinforcement_conflicts_rejects_symlink_target(tmp_path: Path) -> None:
    real_target = tmp_path / "real.json"
    real_target.write_text("{}", encoding="utf-8")
    link_path = tmp_path / "link.json"
    link_path.symlink_to(real_target)

    with pytest.raises(ValueError, match="must not be a symlink"):
        write_highlight_reinforcement_conflicts(
            link_path, HighlightReinforcementConflictSet(()), overwrite=True
        )


def test_highlight_reinforcement_conflicts_atomic_write_preserves_existing_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    original = HighlightReinforcementConflictSet(
        (
            HighlightReinforcementConflict(
                "evt_001", "highlight-a", QualitySelectionMethod.QUALITY_FIRST, 1
            ),
        )
    )
    write_highlight_reinforcement_conflicts(path, original)
    original_payload = path.read_text(encoding="utf-8")
    replacement = HighlightReinforcementConflictSet(
        (
            HighlightReinforcementConflict(
                "evt_001", "highlight-b", QualitySelectionMethod.QUALITY_FIRST, 1
            ),
        )
    )

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(highlight_story_bridge_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_highlight_reinforcement_conflicts(path, replacement, overwrite=True)

    assert path.read_text(encoding="utf-8") == original_payload
    assert not list(tmp_path.glob(".highlight-reinforcement-conflicts.json.*.tmp"))


def test_load_highlight_reinforcement_conflicts_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        load_highlight_reinforcement_conflicts(tmp_path / "missing.json")


def test_load_highlight_reinforcement_conflicts_rejects_symlink(tmp_path: Path) -> None:
    real_target = tmp_path / "real.json"
    write_highlight_reinforcement_conflicts(real_target, HighlightReinforcementConflictSet(()))
    link_path = tmp_path / "link.json"
    link_path.symlink_to(real_target)

    with pytest.raises(ValueError, match="unavailable"):
        load_highlight_reinforcement_conflicts(link_path)


def test_load_highlight_reinforcement_conflicts_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(json.dumps({"schema_version": "other", "conflicts": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_unknown_top_level_field(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [],
                "note": "unexpected",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_unknown_conflict_field(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [
                    {
                        "event_id": "evt_001",
                        "candidate_id": "highlight-a",
                        "method": "01-quality-first",
                        "rank": 1,
                        "note": "extra",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_non_string_identifiers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [
                    {
                        "event_id": "evt_001",
                        "candidate_id": 123,
                        "method": "01-quality-first",
                        "rank": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid schema"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_non_positive_rank(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [
                    {
                        "event_id": "evt_001",
                        "candidate_id": "highlight-a",
                        "method": "01-quality-first",
                        "rank": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rank must be positive"):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_unknown_method(tmp_path: Path) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [
                    {
                        "event_id": "evt_001",
                        "candidate_id": "highlight-a",
                        "method": "not-a-method",
                        "rank": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_highlight_reinforcement_conflicts(path)


def test_load_highlight_reinforcement_conflicts_rejects_repeated_event_candidate_pairing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "highlight-reinforcement-conflicts.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "local-highlight-reinforcement-conflict-v1",
                "conflicts": [
                    {
                        "event_id": "evt_001",
                        "candidate_id": "highlight-a",
                        "method": "01-quality-first",
                        "rank": 1,
                    },
                    {
                        "event_id": "evt_001",
                        "candidate_id": "highlight-a",
                        "method": "01-quality-first",
                        "rank": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not repeat an event/candidate pairing"):
        load_highlight_reinforcement_conflicts(path)
