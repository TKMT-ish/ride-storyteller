"""Tests for UniversalEvent and to_universal_event adapter (app/scout.py)."""

from __future__ import annotations

import dataclasses
import json
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
from app.video.catalog import ResolvedCandidateClip, VideoMatchStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gps_event(
    event_id: str = "evt_001",
    event_type: str = "elevation_change",
    importance_hint: float = 0.70,
    clip_start_offset_s: float = 10.0,
    clip_end_offset_s: float = 40.0,
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=datetime(2026, 8, 10, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 1, 0, 30, tzinfo=UTC),
        location=Location(latitude=-45.03, longitude=168.66),
        importance_hint=importance_hint,
        evidence=("gps",),
        video_query=VideoQuery(
            asset_name_hint="GX010001.MP4",
            clip_start_offset_s=clip_start_offset_s,
            clip_end_offset_s=clip_end_offset_s,
        ),
    )


def _confirmed_clip(event_id: str = "evt_001") -> CandidateClip:
    return CandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        asset_name_hint="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        requested_duration_s=30.0,
        evidence_status=CandidateEvidenceStatus.CONFIRMED,
        evidence_source="human_review",
    )


def _awaiting_clip(event_id: str = "evt_001") -> CandidateClip:
    return CandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        asset_name_hint="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        requested_duration_s=30.0,
        evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
    )


def _rejected_clip(event_id: str = "evt_001") -> CandidateClip:
    return CandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        asset_name_hint="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        requested_duration_s=30.0,
        evidence_status=CandidateEvidenceStatus.REJECTED,
        evidence_source="human_review",
    )


def _matched_resolved(
    event_id: str = "evt_001",
    asset_id: str = "asset-abc",
    start_offset_s: float = 10.0,
    end_offset_s: float = 40.0,
) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=asset_id,
        file_name="GX010001.MP4",
        start_offset_s=start_offset_s,
        end_offset_s=end_offset_s,
        reason="GPS timestamp matched",
    )


def _not_found_resolved(event_id: str = "evt_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
        reason="No catalog entry covers this timestamp",
    )


class _FakeWindowEvidence:
    """Minimal stand-in for HighlightWindowEvidence.window (WindowFeatures)."""

    def __init__(
        self,
        asset_id: str = "asset-abc",
        start_offset_s: float = 15.0,
        duration_s: float = 12.0,
    ) -> None:
        self.asset_id = asset_id
        self.start_offset_s = start_offset_s
        self.duration_s = duration_s


class _FakeEvidence:
    """Minimal stand-in for HighlightWindowEvidence."""

    def __init__(self, window: _FakeWindowEvidence) -> None:
        self.window = window


class _FakeScoredWindow:
    """Minimal stand-in for ScoredHighlightWindow.

    Has evidence.window.{asset_id, start_offset_s, duration_s} as required.
    """

    def __init__(
        self,
        asset_id: str = "asset-abc",
        window_start: float = 15.0,
        window_duration: float = 12.0,
        quality_score: float = 0.80,
        scenic_score: float = 0.75,
        balanced_score: float = 0.77,
    ) -> None:
        self.evidence = _FakeEvidence(
            _FakeWindowEvidence(asset_id, window_start, window_duration)
        )
        self.quality_score = quality_score
        self.scenic_score = scenic_score
        self.balanced_score = balanced_score


# ---------------------------------------------------------------------------
# 1. GPS-only (no CandidateClip, no resolved clip, no scored window)
# ---------------------------------------------------------------------------

def test_gps_only_source_is_unresolved() -> None:
    """Without a resolved clip, source identity must be None."""
    event = to_universal_event(_gps_event())

    assert event.source_asset_id is None
    assert event.source_start_sec is None
    assert event.source_end_sec is None
    assert event.evidence_confirmed is False
    assert event.evidence.video is False


def test_gps_only_requested_interval_comes_from_video_query() -> None:
    gps = _gps_event(clip_start_offset_s=5.0, clip_end_offset_s=35.0)
    event = to_universal_event(gps)

    assert event.requested_start_sec == 5.0
    assert event.requested_end_sec == 35.0


def test_gps_only_scores_are_none() -> None:
    event = to_universal_event(_gps_event())

    assert event.visual_score is None
    assert event.scenic_score is None
    assert event.ranking_score is None


# ---------------------------------------------------------------------------
# 2. CandidateClip alone does NOT resolve source identity
# ---------------------------------------------------------------------------

def test_candidate_clip_alone_does_not_set_source_identity() -> None:
    """CandidateClip carries evidence_status only; it is not a resolved source."""
    event = to_universal_event(_gps_event(), candidate_clip=_confirmed_clip())

    assert event.source_asset_id is None
    assert event.source_start_sec is None
    assert event.source_end_sec is None


def test_candidate_clip_alone_does_not_confirm_evidence() -> None:
    """evidence_confirmed requires BOTH confirmed CandidateClip AND matched resolved clip."""
    event = to_universal_event(_gps_event(), candidate_clip=_confirmed_clip())

    assert event.evidence_confirmed is False


# ---------------------------------------------------------------------------
# 3. ResolvedCandidateClip as source
# ---------------------------------------------------------------------------

def test_matched_resolved_clip_provides_source_identity() -> None:
    resolved = _matched_resolved(asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0)
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_confirmed_clip(),
        resolved_clip=resolved,
    )

    assert event.source_asset_id == "asset-abc"
    assert event.source_start_sec == 10.0
    assert event.source_end_sec == 40.0


def test_matched_resolved_and_confirmed_clip_sets_evidence_confirmed() -> None:
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_confirmed_clip(),
        resolved_clip=_matched_resolved(),
    )

    assert event.evidence_confirmed is True
    assert event.evidence.video is True


def test_awaiting_clip_with_matched_resolved_is_not_confirmed() -> None:
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_awaiting_clip(),
        resolved_clip=_matched_resolved(),
    )

    assert event.evidence_confirmed is False
    assert event.evidence.video is False


def test_rejected_clip_has_video_evidence_but_not_confirmed() -> None:
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_rejected_clip(),
        resolved_clip=_matched_resolved(),
    )

    assert event.evidence_confirmed is False
    assert event.evidence.video is True


def test_requested_interval_is_from_gps_query_not_resolved_clip() -> None:
    """requested_* always comes from GpsEvent.video_query regardless of resolved clip."""
    gps = _gps_event(clip_start_offset_s=5.0, clip_end_offset_s=35.0)
    resolved = _matched_resolved(start_offset_s=12.0, end_offset_s=42.0)

    event = to_universal_event(gps, candidate_clip=_confirmed_clip(), resolved_clip=resolved)

    assert event.requested_start_sec == 5.0
    assert event.requested_end_sec == 35.0
    assert event.source_start_sec == 12.0
    assert event.source_end_sec == 42.0


# ---------------------------------------------------------------------------
# 4. Location context
# ---------------------------------------------------------------------------

def test_location_context_is_populated() -> None:
    ctx = UniversalEventLocationContext(
        place_name="Lindis Pass",
        poi_type="mountain_pass",
        road_context="winding_mountain_road",
        elevation_m=971.0,
    )
    event = to_universal_event(_gps_event(), location_context=ctx)

    assert event.location_context.place_name == "Lindis Pass"
    assert event.location_context.poi_type == "mountain_pass"
    assert event.location_context.road_context == "winding_mountain_road"
    assert event.location_context.elevation_m == 971.0


def test_default_location_context_is_empty() -> None:
    event = to_universal_event(_gps_event())

    assert event.location_context.place_name is None
    assert event.location_context.poi_type is None
    assert event.location_context.road_context is None
    assert event.location_context.elevation_m is None


def test_elevation_evidence_set_when_elevation_m_present() -> None:
    ctx = UniversalEventLocationContext(elevation_m=450.0)
    event = to_universal_event(_gps_event(), location_context=ctx)

    assert event.evidence.elevation is True


def test_elevation_evidence_false_without_elevation() -> None:
    event = to_universal_event(_gps_event())

    assert event.evidence.elevation is False


# ---------------------------------------------------------------------------
# 5. Sub-category
# ---------------------------------------------------------------------------

def test_sub_category_is_passed_through() -> None:
    event = to_universal_event(_gps_event(), sub_category="mountain_pass")

    assert event.sub_category == "mountain_pass"


# ---------------------------------------------------------------------------
# 6. Privacy (required test #16)
# ---------------------------------------------------------------------------

def test_universal_event_contains_no_latitude_or_longitude() -> None:
    """Raw GPS coordinates must never appear in UniversalEvent."""
    ctx = UniversalEventLocationContext(place_name="Lindis Pass", elevation_m=971.0)
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_confirmed_clip(),
        resolved_clip=_matched_resolved(),
        location_context=ctx,
    )
    serialized = json.dumps(dataclasses.asdict(event))
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_universal_event_contains_no_file_name_or_path() -> None:
    """File names, paths, and URIs must not appear in UniversalEvent."""
    event = to_universal_event(
        _gps_event(),
        candidate_clip=_confirmed_clip(),
        resolved_clip=_matched_resolved(),
    )
    serialized = json.dumps(dataclasses.asdict(event))
    assert "file_name" not in serialized
    assert "GX010001.MP4" not in serialized
    assert ".mp4" not in serialized.lower()


def test_location_context_contains_no_raw_coordinates() -> None:
    ctx = UniversalEventLocationContext(
        place_name="Roys Peak", poi_type="summit",
        road_context="gravel_track", elevation_m=1578.0,
    )
    fields = {f.name for f in dataclasses.fields(ctx)}
    assert "latitude" not in fields
    assert "longitude" not in fields


# ---------------------------------------------------------------------------
# 7. UniversalEvent.__post_init__ invariants
# ---------------------------------------------------------------------------

def _valid_unresolved_event(**overrides: object) -> UniversalEvent:
    defaults: dict[str, object] = dict(
        event_id="evt_001",
        event_type="elevation_change",
        sub_category=None,
        source_asset_id=None,
        source_start_sec=None,
        source_end_sec=None,
        requested_start_sec=0.0,
        requested_end_sec=30.0,
        intensity=0.7,
        visual_score=None,
        scenic_score=None,
        ranking_score=None,
        location_context=UniversalEventLocationContext(),
        evidence=UniversalEventEvidence(gps=True, video=False),
        evidence_confirmed=False,
    )
    defaults.update(overrides)
    return UniversalEvent(**defaults)  # type: ignore[arg-type]


def test_rejects_invalid_intensity() -> None:
    with pytest.raises(ValueError, match="intensity"):
        _valid_unresolved_event(intensity=1.5)


def test_rejects_invalid_visual_score() -> None:
    with pytest.raises(ValueError, match="visual_score"):
        _valid_unresolved_event(
            visual_score=-0.1,
            evidence=UniversalEventEvidence(gps=True, video=True),
        )


def test_rejects_invalid_ranking_score() -> None:
    with pytest.raises(ValueError, match="ranking_score"):
        _valid_unresolved_event(
            ranking_score=1.5,
            evidence=UniversalEventEvidence(gps=True, video=True),
        )


def test_rejects_empty_event_id() -> None:
    with pytest.raises(ValueError, match="event_id"):
        _valid_unresolved_event(event_id="")


def test_rejects_inverted_requested_range() -> None:
    with pytest.raises(ValueError, match="requested_end_sec"):
        _valid_unresolved_event(requested_start_sec=30.0, requested_end_sec=10.0)


def test_rejects_partial_source_fields_asset_only() -> None:
    """source_asset_id present but offsets None must fail."""
    with pytest.raises(ValueError, match="all be None"):
        _valid_unresolved_event(source_asset_id="asset-x")


def test_rejects_partial_source_fields_start_only() -> None:
    with pytest.raises(ValueError, match="all be None"):
        _valid_unresolved_event(source_start_sec=5.0)


def test_rejects_partial_source_fields_offsets_without_asset() -> None:
    with pytest.raises(ValueError, match="all be None"):
        _valid_unresolved_event(source_start_sec=5.0, source_end_sec=35.0)


def test_rejects_resolved_source_with_inverted_interval() -> None:
    with pytest.raises(ValueError, match="source_end_sec must be after"):
        _valid_unresolved_event(
            source_asset_id="asset-x",
            source_start_sec=30.0,
            source_end_sec=10.0,
        )


def test_rejects_evidence_confirmed_without_video() -> None:
    with pytest.raises(ValueError, match="evidence_confirmed=True requires evidence.video=True"):
        _valid_unresolved_event(
            evidence=UniversalEventEvidence(gps=True, video=False),
            evidence_confirmed=True,
        )


def test_valid_confirmed_requires_resolved_source() -> None:
    """evidence_confirmed=True without resolved source must raise (required test #1)."""
    with pytest.raises(ValueError, match="requires a resolved source"):
        _valid_unresolved_event(
            source_asset_id=None,
            source_start_sec=None,
            source_end_sec=None,
            evidence=UniversalEventEvidence(gps=True, video=True),
            evidence_confirmed=True,
        )


def test_valid_confirmed_with_resolved_source_succeeds() -> None:
    """evidence_confirmed=True with valid resolved source must succeed (required test #11)."""
    event = _valid_unresolved_event(
        source_asset_id="asset-abc",
        source_start_sec=10.0,
        source_end_sec=40.0,
        evidence=UniversalEventEvidence(gps=True, video=True),
        evidence_confirmed=True,
    )
    assert event.evidence_confirmed is True
    assert event.evidence.video is True
    assert event.source_asset_id == "asset-abc"


def test_rejects_visual_score_without_video_evidence() -> None:
    """visual_score present with evidence.video=False must fail (required test #15)."""
    with pytest.raises(ValueError, match="requires evidence.video=True"):
        _valid_unresolved_event(
            visual_score=0.8,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


def test_rejects_scenic_score_without_video_evidence() -> None:
    with pytest.raises(ValueError, match="requires evidence.video=True"):
        _valid_unresolved_event(
            scenic_score=0.7,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


def test_rejects_ranking_score_without_video_evidence() -> None:
    with pytest.raises(ValueError, match="requires evidence.video=True"):
        _valid_unresolved_event(
            ranking_score=0.75,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


# ---------------------------------------------------------------------------
# 8. Cross-event ID rejection
# ---------------------------------------------------------------------------

def test_mismatched_candidate_clip_event_id_raises() -> None:
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_002")
    with pytest.raises(ValueError, match="does not match"):
        to_universal_event(gps, candidate_clip=clip)


def test_mismatched_resolved_clip_event_id_raises() -> None:
    """Required test #1: resolved_clip.event_id mismatch must raise."""
    gps = _gps_event("evt_001")
    resolved = _matched_resolved("evt_002")
    with pytest.raises(ValueError, match="does not match"):
        to_universal_event(gps, resolved_clip=resolved)


def test_confirmed_clip_wrong_event_cannot_confirm() -> None:
    """Required test #2: CONFIRMED clip for different event must not set confirmed."""
    gps = _gps_event("evt_a")
    clip = _confirmed_clip("evt_b")
    with pytest.raises(ValueError):
        to_universal_event(gps, candidate_clip=clip)


def test_matching_event_ids_confirmed_succeeds() -> None:
    event = to_universal_event(
        _gps_event("evt_001"),
        candidate_clip=_confirmed_clip("evt_001"),
        resolved_clip=_matched_resolved("evt_001"),
    )
    assert event.evidence_confirmed is True


# ---------------------------------------------------------------------------
# 9. NOT_FOUND resolved clip rejected as source (required test #2)
# ---------------------------------------------------------------------------

def test_not_found_resolved_clip_raises_as_source() -> None:
    """Required test #2: NOT_FOUND resolved clip must not provide source identity."""
    gps = _gps_event("evt_001")
    resolved = _not_found_resolved("evt_001")
    with pytest.raises(ValueError, match="only MATCHED clips provide source identity"):
        to_universal_event(gps, candidate_clip=_confirmed_clip(), resolved_clip=resolved)


# ---------------------------------------------------------------------------
# 10. scored_window prerequisite failures (required tests #3, #4)
# ---------------------------------------------------------------------------

def test_scored_window_without_candidate_clip_raises() -> None:
    """Required test #3: scored_window without candidate_clip must raise."""
    gps = _gps_event("evt_001")
    resolved = _matched_resolved("evt_001")
    window = _FakeScoredWindow(asset_id="asset-abc")
    with pytest.raises(ValueError, match="scored_window requires candidate_clip"):
        to_universal_event(gps, resolved_clip=resolved, scored_window=window)  # type: ignore[arg-type]


def test_scored_window_without_resolved_clip_raises() -> None:
    """scored_window without resolved_clip must raise."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    window = _FakeScoredWindow(asset_id="asset-abc")
    with pytest.raises(ValueError, match="scored_window requires resolved_clip"):
        to_universal_event(gps, candidate_clip=clip, scored_window=window)  # type: ignore[arg-type]


def test_scored_window_asset_id_mismatch_raises() -> None:
    """Required test #4: window asset_id != resolved_clip.asset_id must raise."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    window = _FakeScoredWindow(asset_id="different-asset", window_start=15.0, window_duration=12.0)
    with pytest.raises(ValueError, match="does not match"):
        to_universal_event(gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 11. scored_window interval containment (required tests #5, #6, #7, #8)
# ---------------------------------------------------------------------------

def test_scored_window_starting_before_resolved_raises() -> None:
    """Required test #5: window starting before resolved clip start must raise."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    # window starts at 5.0, before resolved start 10.0
    window = _FakeScoredWindow(asset_id="asset-abc", window_start=5.0, window_duration=12.0)
    with pytest.raises(ValueError, match="before"):
        to_universal_event(gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window)  # type: ignore[arg-type]


def test_scored_window_ending_after_resolved_raises() -> None:
    """Required test #6: window extending past resolved clip end must raise."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    # window starts at 35.0, duration 12.0 → ends at 47.0, after resolved end 40.0
    window = _FakeScoredWindow(asset_id="asset-abc", window_start=35.0, window_duration=12.0)
    with pytest.raises(ValueError, match="after"):
        to_universal_event(gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window)  # type: ignore[arg-type]


def test_scored_window_contained_within_resolved_is_accepted() -> None:
    """Required test #7: window fully within resolved clip must succeed."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    # window 15.0–27.0, fully inside 10.0–40.0
    window = _FakeScoredWindow(asset_id="asset-abc", window_start=15.0, window_duration=12.0)
    event = to_universal_event(  # type: ignore[call-arg]
        gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window,
    )
    assert event.source_asset_id == "asset-abc"
    assert event.source_start_sec == pytest.approx(15.0)
    assert event.source_end_sec == pytest.approx(27.0)


def test_scored_window_becomes_source_interval() -> None:
    """Required test #8: accepted window interval replaces resolved clip interval."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    window = _FakeScoredWindow(asset_id="asset-abc", window_start=18.0, window_duration=12.0)

    event = to_universal_event(  # type: ignore[call-arg]
        gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window,
    )

    # Source interval is window (18–30), not resolved (10–40)
    assert event.source_start_sec == pytest.approx(18.0)
    assert event.source_end_sec == pytest.approx(30.0)
    # Requested interval remains from GPS query
    assert event.requested_start_sec == 10.0
    assert event.requested_end_sec == 40.0


# ---------------------------------------------------------------------------
# 12. scored_window with evidence flags (required tests #12, #13)
# ---------------------------------------------------------------------------

def test_scored_window_sets_video_evidence_true() -> None:
    """Required test #12: accepted scored_window sets evidence.video=True."""
    gps = _gps_event("evt_001")
    clip = _awaiting_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    window = _FakeScoredWindow(asset_id="asset-abc", window_start=15.0, window_duration=12.0)

    event = to_universal_event(  # type: ignore[call-arg]
        gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window,
    )

    assert event.evidence.video is True
    assert event.evidence_confirmed is False  # awaiting, not confirmed


def test_scored_window_alone_does_not_confirm_evidence() -> None:
    """Required test #13: scored_window with awaiting clip must not set confirmed."""
    gps = _gps_event("evt_001")
    clip = _awaiting_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    window = _FakeScoredWindow(
        asset_id="asset-abc", window_start=15.0, window_duration=12.0,
        quality_score=0.99, scenic_score=0.99, balanced_score=0.99,
    )

    event = to_universal_event(  # type: ignore[call-arg]
        gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window,
    )

    assert event.evidence_confirmed is False
    assert event.visual_score == pytest.approx(0.99)


def test_confirmed_clip_matched_resolved_and_window_all_confirmed() -> None:
    """Required test #14: CONFIRMED clip + MATCHED resolved + window = confirmed."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")
    resolved = _matched_resolved(
        "evt_001", asset_id="asset-abc", start_offset_s=10.0, end_offset_s=40.0
    )
    window = _FakeScoredWindow(
        asset_id="asset-abc", window_start=15.0, window_duration=12.0,
        quality_score=0.85, scenic_score=0.80, balanced_score=0.82,
    )

    event = to_universal_event(  # type: ignore[call-arg]
        gps, candidate_clip=clip, resolved_clip=resolved, scored_window=window,
    )

    assert event.evidence_confirmed is True
    assert event.evidence.video is True
    assert event.visual_score == pytest.approx(0.85)
    assert event.scenic_score == pytest.approx(0.80)
    assert event.ranking_score == pytest.approx(0.82)


# ---------------------------------------------------------------------------
# 13. Director input contract: only confirmed events
# ---------------------------------------------------------------------------

def test_only_confirmed_events_are_director_ready() -> None:
    """Director input must be filtered to evidence_confirmed=True only."""
    events_and_clips = [
        (
            _gps_event("evt_confirmed"),
            _confirmed_clip("evt_confirmed"),
            _matched_resolved("evt_confirmed"),
        ),
        (
            _gps_event("evt_awaiting"),
            _awaiting_clip("evt_awaiting"),
            _matched_resolved("evt_awaiting"),
        ),
        (
            _gps_event("evt_rejected"),
            _rejected_clip("evt_rejected"),
            _matched_resolved("evt_rejected"),
        ),
    ]
    universal = tuple(
        to_universal_event(gps, candidate_clip=clip, resolved_clip=res)
        for gps, clip, res in events_and_clips
    )
    director_input = tuple(u for u in universal if u.evidence_confirmed)

    assert len(director_input) == 1
    assert director_input[0].event_id == "evt_confirmed"


# ---------------------------------------------------------------------------
# 14. ranking_score field name
# ---------------------------------------------------------------------------

def test_ranking_score_field_exists_not_confidence() -> None:
    fields = {f.name for f in dataclasses.fields(UniversalEvent)}
    assert "ranking_score" in fields
    assert "confidence" not in fields


# ---------------------------------------------------------------------------
# 15. NEW invariants: confirmed/score require resolved source (required tests #1-4)
# ---------------------------------------------------------------------------

def test_visual_score_with_video_but_no_source_raises() -> None:
    """Required test #2: visual_score + evidence.video=True + source None → ValueError."""
    with pytest.raises(ValueError, match="requires a resolved source"):
        _valid_unresolved_event(
            source_asset_id=None,
            source_start_sec=None,
            source_end_sec=None,
            visual_score=0.8,
            evidence=UniversalEventEvidence(gps=True, video=True),
        )


def test_scenic_score_with_video_but_no_source_raises() -> None:
    """Required test #3: scenic_score + evidence.video=True + source None → ValueError."""
    with pytest.raises(ValueError, match="requires a resolved source"):
        _valid_unresolved_event(
            source_asset_id=None,
            source_start_sec=None,
            source_end_sec=None,
            scenic_score=0.75,
            evidence=UniversalEventEvidence(gps=True, video=True),
        )


def test_ranking_score_with_video_but_no_source_raises() -> None:
    """Required test #4: ranking_score + evidence.video=True + source None → ValueError."""
    with pytest.raises(ValueError, match="requires a resolved source"):
        _valid_unresolved_event(
            source_asset_id=None,
            source_start_sec=None,
            source_end_sec=None,
            ranking_score=0.77,
            evidence=UniversalEventEvidence(gps=True, video=True),
        )


def test_visual_score_with_resolved_source_succeeds() -> None:
    """Required test #12: visual_score with valid resolved source must succeed."""
    event = _valid_unresolved_event(
        source_asset_id="asset-abc",
        source_start_sec=10.0,
        source_end_sec=40.0,
        visual_score=0.8,
        scenic_score=0.75,
        ranking_score=0.77,
        evidence=UniversalEventEvidence(gps=True, video=True),
    )
    assert event.visual_score == pytest.approx(0.8)
    assert event.scenic_score == pytest.approx(0.75)
    assert event.ranking_score == pytest.approx(0.77)
    assert event.source_asset_id == "asset-abc"


# ---------------------------------------------------------------------------
# 16. NEW: chapter_id consistency check (required tests #5, #6)
# ---------------------------------------------------------------------------

def test_candidate_and_resolved_same_event_different_chapter_raises() -> None:
    """Required test #5: same event_id but different chapter_id must raise."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")  # chapter_id = "chapter_01"
    resolved = ResolvedCandidateClip(
        chapter_id="chapter_02",         # different chapter
        event_id="evt_001",
        status=VideoMatchStatus.MATCHED,
        asset_id="asset-abc",
        file_name="GX010001.MP4",
        start_offset_s=10.0,
        end_offset_s=40.0,
        reason="matched",
    )
    with pytest.raises(ValueError, match="chapter_id.*does not match"):
        to_universal_event(gps, candidate_clip=clip, resolved_clip=resolved)


def test_candidate_and_resolved_same_event_same_chapter_succeeds() -> None:
    """Required test #6: same event_id and same chapter_id must succeed."""
    gps = _gps_event("evt_001")
    clip = _confirmed_clip("evt_001")   # chapter_id = "chapter_01"
    resolved = _matched_resolved("evt_001")   # chapter_id = "chapter_01"
    event = to_universal_event(gps, candidate_clip=clip, resolved_clip=resolved)
    assert event.evidence_confirmed is True


# ---------------------------------------------------------------------------
# 17. NEW: source_asset_id content validation (required tests #7, #8)
# ---------------------------------------------------------------------------

def test_source_asset_id_empty_string_raises() -> None:
    """Required test #7: source_asset_id="" must raise."""
    with pytest.raises(ValueError, match="non-empty, non-whitespace"):
        _valid_unresolved_event(
            source_asset_id="",
            source_start_sec=10.0,
            source_end_sec=40.0,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


def test_source_asset_id_whitespace_only_raises() -> None:
    """Required test #8: source_asset_id="   " must raise."""
    with pytest.raises(ValueError, match="non-empty, non-whitespace"):
        _valid_unresolved_event(
            source_asset_id="   ",
            source_start_sec=10.0,
            source_end_sec=40.0,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


# ---------------------------------------------------------------------------
# 18. NEW: source_start_sec non-negative (required test #9)
# ---------------------------------------------------------------------------

def test_source_start_sec_negative_raises() -> None:
    """Required test #9: source_start_sec < 0 must raise."""
    with pytest.raises(ValueError, match="source_start_sec must be non-negative"):
        _valid_unresolved_event(
            source_asset_id="asset-abc",
            source_start_sec=-1.0,
            source_end_sec=10.0,
            evidence=UniversalEventEvidence(gps=True, video=False),
        )


# ---------------------------------------------------------------------------
# 19. NEW: requested_start_sec non-negative (required test #10)
# ---------------------------------------------------------------------------

def test_requested_start_sec_negative_raises() -> None:
    """Required test #10: requested_start_sec < 0 must raise."""
    with pytest.raises(ValueError, match="requested_start_sec must be non-negative"):
        _valid_unresolved_event(requested_start_sec=-1.0, requested_end_sec=30.0)
