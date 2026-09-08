"""Boundary and failure-path tests for ``app.scout``.

All fixtures here are synthetic: no real footage, GPS traces, GCS objects,
or Gemini calls are involved. The point of these tests is to pin down the
contract described in ``app/scout.py``'s module docstring — the two-line
evidence gate, the all-or-nothing source fields, and the privacy invariant
that raw coordinates and file identity never reach ``UniversalEvent``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from app.contracts import GpsEvent, Location, VideoQuery
from app.edit.candidate_planner import CandidateClip, CandidateEvidenceStatus
from app.scout import (
    UniversalEvent,
    UniversalEventEvidence,
    UniversalEventLocationContext,
    to_universal_event,
)
from app.video.apple_vision import VisionClassification, VisionImageAnalysis
from app.video.catalog import ResolvedCandidateClip, VideoMatchStatus
from app.video.gpmf_metrics import GpmfWindowSummary
from app.video.highlight_discovery import WindowFeatures
from app.video.highlight_quality import HighlightWindowEvidence, ScoredHighlightWindow

_START = datetime(2026, 8, 30, 9, 0, 0, tzinfo=UTC)
_END = datetime(2026, 8, 30, 9, 0, 12, tzinfo=UTC)


def _gps_event(
    *,
    event_id: str = "event-1",
    event_type: str = "stop",
    query_start: float = 0.0,
    query_end: float = 10.0,
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=_START,
        end_time=_END,
        location=Location(35.1, 139.1),
        importance_hint=0.5,
        evidence=("gps_stop",),
        video_query=VideoQuery(
            asset_name_hint="ride.mp4",
            clip_start_offset_s=query_start,
            clip_end_offset_s=query_end,
        ),
    )


def _candidate_clip(
    *,
    event_id: str = "event-1",
    chapter_id: str = "chapter-1",
    status: CandidateEvidenceStatus = CandidateEvidenceStatus.CONFIRMED,
    evidence_source: str | None = "video_review",
) -> CandidateClip:
    return CandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        asset_name_hint="ride.mp4",
        start_offset_s=0.0,
        end_offset_s=10.0,
        requested_duration_s=10.0,
        evidence_status=status,
        evidence_source=(
            None if status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE else evidence_source
        ),
    )


def _resolved_clip(
    *,
    event_id: str = "event-1",
    chapter_id: str = "chapter-1",
    status: VideoMatchStatus = VideoMatchStatus.MATCHED,
    asset_id: str | None = "asset-1",
    start_offset_s: float | None = 0.0,
    end_offset_s: float | None = 10.0,
) -> ResolvedCandidateClip:
    if status is VideoMatchStatus.MATCHED:
        return ResolvedCandidateClip(
            chapter_id=chapter_id,
            event_id=event_id,
            status=status,
            asset_id=asset_id,
            file_name="GX010001.MP4",
            start_offset_s=start_offset_s,
            end_offset_s=end_offset_s,
            reason="matched by timestamp",
        )
    return ResolvedCandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        status=status,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="no asset covers this window",
    )


def _scored_window(
    *,
    asset_id: str = "asset-1",
    start_offset_s: float = 2.0,
    duration_s: float = 6.0,
    score: float = 0.7,
) -> ScoredHighlightWindow:
    window = WindowFeatures(
        asset_id=asset_id,
        start_offset_s=start_offset_s,
        duration_s=duration_s,
        timeline_s=_START.timestamp(),
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
    )
    frames = tuple(
        VisionImageAnalysis(
            index=index,
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
    return ScoredHighlightWindow(
        evidence=evidence,
        interest_lanes=(),
        quality_score=score,
        dynamics_score=score,
        scenic_score=score,
        balanced_score=score,
    )


# ---------------------------------------------------------------------------
# to_universal_event: minimal / GPS-only path
# ---------------------------------------------------------------------------


def test_gps_only_event_has_no_source_and_unconfirmed_evidence():
    event = to_universal_event(_gps_event())
    assert event.source_asset_id is None
    assert event.source_start_sec is None
    assert event.source_end_sec is None
    assert event.evidence_confirmed is False
    assert event.evidence.gps is True
    assert event.evidence.video is False
    assert event.evidence.elevation is False
    assert event.visual_score is None
    assert event.scenic_score is None
    assert event.ranking_score is None


def test_requested_interval_comes_from_video_query():
    event = to_universal_event(_gps_event(query_start=3.0, query_end=9.0))
    assert event.requested_start_sec == 3.0
    assert event.requested_end_sec == 9.0


def test_sub_category_and_location_context_pass_through():
    context = UniversalEventLocationContext(
        place_name="mountain pass", poi_type="scenic_overlook", elevation_m=812.0
    )
    event = to_universal_event(_gps_event(), location_context=context, sub_category="mountain_pass")
    assert event.sub_category == "mountain_pass"
    assert event.location_context is context
    assert event.evidence.elevation is True


def test_default_location_context_has_no_elevation_evidence():
    event = to_universal_event(_gps_event())
    assert event.location_context == UniversalEventLocationContext()
    assert event.evidence.elevation is False


# ---------------------------------------------------------------------------
# Contract 1 & 2: event_id agreement across candidate_clip / resolved_clip
# ---------------------------------------------------------------------------


def test_candidate_clip_event_id_mismatch_raises():
    with pytest.raises(ValueError, match="candidate_clip.event_id"):
        to_universal_event(
            _gps_event(event_id="event-1"),
            candidate_clip=_candidate_clip(event_id="event-2"),
        )


def test_resolved_clip_event_id_mismatch_raises():
    with pytest.raises(ValueError, match="resolved_clip.event_id"):
        to_universal_event(
            _gps_event(event_id="event-1"),
            resolved_clip=_resolved_clip(event_id="event-2"),
        )


def test_candidate_and_resolved_chapter_id_mismatch_raises():
    with pytest.raises(ValueError, match="chapter_id"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(chapter_id="chapter-a"),
            resolved_clip=_resolved_clip(chapter_id="chapter-b"),
        )


# ---------------------------------------------------------------------------
# Contract 3: source identity only from a MATCHED resolved clip
# ---------------------------------------------------------------------------


def test_not_found_resolved_clip_is_rejected_as_a_source():
    """A NOT_FOUND clip is never a valid source; the adapter refuses it
    outright rather than silently leaving the event unresolved."""
    with pytest.raises(ValueError, match="only MATCHED clips provide source identity"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE),
            resolved_clip=_resolved_clip(status=VideoMatchStatus.NOT_FOUND),
        )


def test_matched_resolved_clip_supplies_source_identity():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(),
        resolved_clip=_resolved_clip(start_offset_s=1.0, end_offset_s=11.0),
    )
    assert event.source_asset_id == "asset-1"
    assert event.source_start_sec == 1.0
    assert event.source_end_sec == 11.0


# ---------------------------------------------------------------------------
# Contract 4: scored_window prerequisites and containment
# ---------------------------------------------------------------------------


def test_scored_window_without_candidate_clip_raises():
    with pytest.raises(ValueError, match="scored_window requires candidate_clip"):
        to_universal_event(
            _gps_event(),
            resolved_clip=_resolved_clip(),
            scored_window=_scored_window(),
        )


def test_scored_window_without_resolved_clip_raises():
    with pytest.raises(ValueError, match="scored_window requires resolved_clip"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(),
            scored_window=_scored_window(),
        )


def test_scored_window_asset_id_mismatch_raises():
    with pytest.raises(ValueError, match="asset_id"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(),
            resolved_clip=_resolved_clip(asset_id="asset-1"),
            scored_window=_scored_window(asset_id="asset-2"),
        )


def test_scored_window_starting_before_resolved_clip_raises():
    with pytest.raises(ValueError, match="before"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(),
            resolved_clip=_resolved_clip(start_offset_s=2.0, end_offset_s=10.0),
            scored_window=_scored_window(start_offset_s=1.0, duration_s=2.0),
        )


def test_scored_window_ending_after_resolved_clip_raises():
    with pytest.raises(ValueError, match="after"):
        to_universal_event(
            _gps_event(),
            candidate_clip=_candidate_clip(),
            resolved_clip=_resolved_clip(start_offset_s=0.0, end_offset_s=6.0),
            scored_window=_scored_window(start_offset_s=2.0, duration_s=6.0),
        )


def test_scored_window_exactly_at_resolved_clip_boundary_is_accepted():
    """The window may span the resolved clip's full interval exactly;
    the tolerance exists for float rounding, not to reject exact equality."""
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(),
        resolved_clip=_resolved_clip(start_offset_s=0.0, end_offset_s=6.0),
        scored_window=_scored_window(start_offset_s=0.0, duration_s=6.0),
    )
    assert event.source_start_sec == 0.0
    assert event.source_end_sec == 6.0


def test_scored_window_replaces_resolved_interval_and_carries_scores():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(),
        resolved_clip=_resolved_clip(start_offset_s=0.0, end_offset_s=10.0),
        scored_window=_scored_window(start_offset_s=2.0, duration_s=6.0, score=0.81),
    )
    assert event.source_start_sec == 2.0
    assert event.source_end_sec == 8.0
    assert event.visual_score == 0.81
    assert event.scenic_score == 0.81
    assert event.ranking_score == 0.81


def test_scored_window_implies_video_evidence_even_when_candidate_not_confirmed():
    """A verified scored_window is itself proof a video match happened,
    independent of whether the candidate's own status is CONFIRMED."""
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE),
        resolved_clip=_resolved_clip(),
        scored_window=_scored_window(),
    )
    assert event.evidence.video is True
    assert event.evidence_confirmed is False


# ---------------------------------------------------------------------------
# Contract 5: evidence_confirmed requires both CONFIRMED and MATCHED
# ---------------------------------------------------------------------------


def test_evidence_confirmed_true_only_when_confirmed_and_matched():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(status=CandidateEvidenceStatus.CONFIRMED),
        resolved_clip=_resolved_clip(status=VideoMatchStatus.MATCHED),
    )
    assert event.evidence_confirmed is True
    assert event.evidence.video is True


def test_rejected_candidate_has_video_evidence_but_not_confirmed():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(status=CandidateEvidenceStatus.REJECTED),
        resolved_clip=_resolved_clip(status=VideoMatchStatus.MATCHED),
    )
    assert event.evidence_confirmed is False
    assert event.evidence.video is True


def test_awaiting_candidate_without_resolved_clip_has_no_video_evidence():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE),
    )
    assert event.evidence_confirmed is False
    assert event.evidence.video is False


# ---------------------------------------------------------------------------
# Privacy invariant: no raw coordinates or file identity anywhere in the
# UniversalEvent field set.
# ---------------------------------------------------------------------------


def test_universal_event_never_carries_raw_coordinates_or_file_identity():
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_candidate_clip(),
        resolved_clip=_resolved_clip(),
        location_context=UniversalEventLocationContext(place_name="a lookout"),
    )
    field_names = {f.name for f in dataclasses.fields(event)}
    forbidden = {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "file_name",
        "asset_name_hint",
        "source_uri",
        "path",
    }
    assert field_names.isdisjoint(forbidden)
    # source_asset_id is the only source identifier, and it is opaque
    # (an asset_id from the catalog, never a path or file name).
    assert event.source_asset_id == "asset-1"


def test_universal_event_evidence_and_location_context_are_flat_dataclasses():
    """Nested contract objects only carry named semantic fields, never a
    reference back to raw GPS or file-system identity."""
    evidence_fields = {f.name for f in dataclasses.fields(UniversalEventEvidence)}
    location_fields = {f.name for f in dataclasses.fields(UniversalEventLocationContext)}
    assert evidence_fields == {"gps", "video", "map", "poi", "elevation"}
    assert location_fields == {"place_name", "poi_type", "road_context", "elevation_m"}


# ---------------------------------------------------------------------------
# UniversalEvent.__post_init__ invariants, exercised directly
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        event_id="event-1",
        event_type="stop",
        sub_category=None,
        source_asset_id=None,
        source_start_sec=None,
        source_end_sec=None,
        requested_start_sec=0.0,
        requested_end_sec=10.0,
        intensity=0.5,
        visual_score=None,
        scenic_score=None,
        ranking_score=None,
        location_context=UniversalEventLocationContext(),
        evidence=UniversalEventEvidence(gps=True, video=False),
        evidence_confirmed=False,
    )
    base.update(overrides)
    return base


def test_missing_event_id_raises():
    with pytest.raises(ValueError, match="event_id and event_type"):
        UniversalEvent(**_valid_kwargs(event_id=""))


def test_missing_event_type_raises():
    with pytest.raises(ValueError, match="event_id and event_type"):
        UniversalEvent(**_valid_kwargs(event_type=""))


def test_negative_requested_start_raises():
    with pytest.raises(ValueError, match="requested_start_sec"):
        UniversalEvent(**_valid_kwargs(requested_start_sec=-1.0))


def test_requested_end_before_start_raises():
    with pytest.raises(ValueError, match="requested_end_sec"):
        UniversalEvent(**_valid_kwargs(requested_start_sec=5.0, requested_end_sec=4.0))


def test_requested_end_equal_to_start_is_allowed():
    event = UniversalEvent(**_valid_kwargs(requested_start_sec=5.0, requested_end_sec=5.0))
    assert event.requested_end_sec == 5.0


@pytest.mark.parametrize("intensity", [-0.01, 1.01])
def test_intensity_out_of_range_raises(intensity):
    with pytest.raises(ValueError, match="intensity"):
        UniversalEvent(**_valid_kwargs(intensity=intensity))


@pytest.mark.parametrize("intensity", [0.0, 1.0])
def test_intensity_at_bounds_is_allowed(intensity):
    event = UniversalEvent(**_valid_kwargs(intensity=intensity))
    assert event.intensity == intensity


@pytest.mark.parametrize("field", ["visual_score", "scenic_score", "ranking_score"])
def test_score_out_of_range_raises(field):
    with pytest.raises(ValueError, match=field):
        UniversalEvent(
            **_valid_kwargs(
                **{
                    field: 1.5,
                    "source_asset_id": "asset-1",
                    "source_start_sec": 0.0,
                    "source_end_sec": 5.0,
                    "evidence": UniversalEventEvidence(gps=True, video=True),
                }
            )
        )


def test_source_fields_partially_set_raises():
    with pytest.raises(ValueError, match="all be None"):
        UniversalEvent(
            **_valid_kwargs(source_asset_id="asset-1", source_start_sec=None, source_end_sec=5.0)
        )


def test_source_asset_id_blank_raises():
    with pytest.raises(ValueError, match="non-empty"):
        UniversalEvent(
            **_valid_kwargs(
                source_asset_id="   ",
                source_start_sec=0.0,
                source_end_sec=5.0,
                evidence=UniversalEventEvidence(gps=True, video=True),
            )
        )


def test_source_start_negative_raises():
    with pytest.raises(ValueError, match="source_start_sec"):
        UniversalEvent(
            **_valid_kwargs(
                source_asset_id="asset-1",
                source_start_sec=-1.0,
                source_end_sec=5.0,
                evidence=UniversalEventEvidence(gps=True, video=True),
            )
        )


def test_source_end_not_after_start_raises():
    with pytest.raises(ValueError, match="source_end_sec"):
        UniversalEvent(
            **_valid_kwargs(
                source_asset_id="asset-1",
                source_start_sec=5.0,
                source_end_sec=5.0,
                evidence=UniversalEventEvidence(gps=True, video=True),
            )
        )


def test_evidence_confirmed_without_video_evidence_raises():
    with pytest.raises(ValueError, match="evidence.video=True"):
        UniversalEvent(
            **_valid_kwargs(
                source_asset_id="asset-1",
                source_start_sec=0.0,
                source_end_sec=5.0,
                evidence=UniversalEventEvidence(gps=True, video=False),
                evidence_confirmed=True,
            )
        )


def test_evidence_confirmed_without_resolved_source_raises():
    with pytest.raises(ValueError, match="resolved source"):
        UniversalEvent(
            **_valid_kwargs(
                evidence=UniversalEventEvidence(gps=True, video=True),
                evidence_confirmed=True,
            )
        )


def test_score_without_video_evidence_raises():
    with pytest.raises(ValueError, match="evidence.video=True"):
        UniversalEvent(
            **_valid_kwargs(
                source_asset_id="asset-1",
                source_start_sec=0.0,
                source_end_sec=5.0,
                visual_score=0.5,
                evidence=UniversalEventEvidence(gps=True, video=False),
            )
        )


def test_score_without_resolved_source_raises():
    with pytest.raises(ValueError, match="resolved source"):
        UniversalEvent(
            **_valid_kwargs(
                ranking_score=0.5,
                evidence=UniversalEventEvidence(gps=True, video=True),
            )
        )
