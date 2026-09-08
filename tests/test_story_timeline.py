"""Synthetic-fixture tests for the chronological story timeline (Gate 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_timeline import (
    DEFAULT_GAP_CARD_MAXIMUM_S,
    DEFAULT_GAP_CARD_MINIMUM_S,
    StoryBeat,
    StoryBeatKind,
    StoryTimeline,
    StoryTimelineError,
    TimelineFootage,
    build_story_timeline,
    gap_card_screen_duration_s,
)

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _footage(event_id: str, start_offset_s: float, duration_s: float = 30.0) -> TimelineFootage:
    return TimelineFootage(
        event_id=event_id,
        start_time=_at(start_offset_s),
        end_time=_at(start_offset_s + duration_s),
    )


def _gap(
    start_offset_s: float,
    end_offset_s: float,
    kind: JourneyGapKind = JourneyGapKind.BETWEEN_CLIPS,
) -> JourneyGapSegment:
    return JourneyGapSegment(
        kind=kind,
        start_time=_at(start_offset_s),
        end_time=_at(end_offset_s),
        distance_m=1_000.0,
        elevation_gain_m=10.0,
        elevation_loss_m=5.0,
    )


def test_footage_and_gaps_interleave_in_ride_order() -> None:
    timeline = build_story_timeline(
        (_footage("evt_b", 3600.0), _footage("evt_a", 600.0)),
        JourneyGapPlan(
            (
                _gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),
                _gap(630.0, 3600.0),
                _gap(3630.0, 7200.0, JourneyGapKind.AFTER_LAST_CLIP),
            )
        ),
    )

    assert [beat.kind for beat in timeline.beats] == [
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
    ]
    assert [beat.event_id for beat in timeline.footage_beats] == ["evt_a", "evt_b"]


def test_footage_keeps_its_own_length_and_gaps_are_bounded() -> None:
    timeline = build_story_timeline(
        (_footage("evt_a", 600.0, duration_s=30.0),),
        JourneyGapPlan((_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
    )

    footage_beat, *_ = timeline.footage_beats
    gap_beat, *_ = timeline.gap_beats
    assert footage_beat.screen_duration_s == pytest.approx(30.0)
    assert DEFAULT_GAP_CARD_MINIMUM_S <= gap_beat.screen_duration_s <= DEFAULT_GAP_CARD_MAXIMUM_S


def test_screen_time_is_not_ride_time() -> None:
    """A long stretch of riding must not become a long card."""
    long_gap = _gap(0.0, 4 * 3600.0, JourneyGapKind.BEFORE_FIRST_CLIP)

    assert gap_card_screen_duration_s(long_gap) == pytest.approx(DEFAULT_GAP_CARD_MAXIMUM_S)
    assert gap_card_screen_duration_s(_gap(0.0, 90.0)) == pytest.approx(DEFAULT_GAP_CARD_MINIMUM_S)
    # Between the bounds the mapping is proportional: 20 minutes -> 5 seconds.
    assert gap_card_screen_duration_s(_gap(0.0, 1200.0)) == pytest.approx(5.0)


def test_totals_separate_footage_from_whole_film() -> None:
    timeline = build_story_timeline(
        (_footage("evt_a", 600.0), _footage("evt_b", 3600.0)),
        JourneyGapPlan((_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
    )

    assert timeline.footage_screen_duration_s == pytest.approx(60.0)
    assert timeline.total_screen_duration_s > timeline.footage_screen_duration_s


def test_a_ride_with_no_footage_is_still_a_timeline() -> None:
    timeline = build_story_timeline(
        (),
        JourneyGapPlan((_gap(0.0, 1200.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
    )

    assert [beat.kind for beat in timeline.beats] == [StoryBeatKind.GAP_CARD]
    assert timeline.footage_screen_duration_s == pytest.approx(0.0)


def test_a_fully_covered_ride_is_all_footage() -> None:
    timeline = build_story_timeline((_footage("evt_a", 0.0),), JourneyGapPlan(()))

    assert [beat.kind for beat in timeline.beats] == [StoryBeatKind.FOOTAGE]


def test_serialized_timeline_carries_no_private_detail() -> None:
    timeline = build_story_timeline(
        (_footage("evt_private_alpha", 600.0),),
        JourneyGapPlan((_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
    )

    payload = timeline.to_dict()
    serialized = json.dumps(payload)

    assert payload["footage_beat_count"] == 1
    assert payload["gap_beat_count"] == 1
    for forbidden in ("evt_private_alpha", "2026-05-01", "latitude", "longitude"):
        assert forbidden not in serialized
    assert set(payload["beats"][1]) == {"kind", "screen_duration_s", "ride_duration_s"}


def test_overlapping_footage_and_gap_fails_closed() -> None:
    with pytest.raises(StoryTimelineError, match="overlap"):
        build_story_timeline(
            (_footage("evt_a", 300.0, duration_s=600.0),),
            JourneyGapPlan((_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
        )


def test_reused_event_fails_closed() -> None:
    with pytest.raises(StoryTimelineError, match="reuse one event"):
        build_story_timeline(
            (_footage("evt_a", 0.0), _footage("evt_a", 600.0)),
            JourneyGapPlan(()),
        )


def test_empty_input_fails_closed() -> None:
    with pytest.raises(StoryTimelineError, match="footage or an uncovered stretch"):
        build_story_timeline((), JourneyGapPlan(()))


def test_invalid_card_bounds_fail_closed() -> None:
    with pytest.raises(StoryTimelineError, match="bounds are invalid"):
        gap_card_screen_duration_s(_gap(0.0, 600.0), minimum_s=0.0)
    with pytest.raises(StoryTimelineError, match="bounds are invalid"):
        gap_card_screen_duration_s(_gap(0.0, 600.0), minimum_s=8.0, maximum_s=3.0)
    with pytest.raises(StoryTimelineError, match="bounds are invalid"):
        gap_card_screen_duration_s(_gap(0.0, 600.0), ratio=0.0)


def test_footage_record_rejects_an_empty_or_reversed_span() -> None:
    with pytest.raises(ValueError, match="event ID"):
        TimelineFootage(event_id="", start_time=_at(0.0), end_time=_at(30.0))
    with pytest.raises(ValueError, match="positive duration"):
        TimelineFootage(event_id="evt_a", start_time=_at(30.0), end_time=_at(0.0))


def test_footage_record_rejects_a_zero_length_span() -> None:
    """The reversed-span check is `<=`, not `<`: equal start and end must fail too."""
    with pytest.raises(ValueError, match="positive duration"):
        TimelineFootage(event_id="evt_a", start_time=_at(30.0), end_time=_at(30.0))


def test_footage_record_rejects_a_negative_source_offset() -> None:
    with pytest.raises(ValueError, match="cannot begin before its window"):
        TimelineFootage(
            event_id="evt_a", start_time=_at(0.0), end_time=_at(30.0), source_offset_s=-0.01
        )


def test_footage_record_accepts_a_zero_source_offset() -> None:
    """Zero is the allowed floor, not itself rejected by the `< 0` check."""
    footage = TimelineFootage(
        event_id="evt_a", start_time=_at(0.0), end_time=_at(30.0), source_offset_s=0.0
    )
    assert footage.source_offset_s == 0.0


def test_footage_record_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 5, 1, 9, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        TimelineFootage(event_id="evt_a", start_time=naive, end_time=_at(30.0))
    with pytest.raises(ValueError, match="timezone-aware"):
        TimelineFootage(event_id="evt_a", start_time=_at(0.0), end_time=naive)


def test_footage_record_duration_property() -> None:
    footage = _footage("evt_a", 0.0, duration_s=45.0)
    assert footage.duration_s == pytest.approx(45.0)


def test_story_beat_rejects_a_non_positive_screen_duration() -> None:
    with pytest.raises(ValueError, match="screen duration must be positive"):
        StoryBeat(
            kind=StoryBeatKind.FOOTAGE,
            ride_start_time=_at(0.0),
            ride_end_time=_at(30.0),
            screen_duration_s=0.0,
            event_id="evt_a",
        )


def test_story_beat_rejects_a_non_positive_ride_span() -> None:
    """Boundary is `<=`: equal start and end must fail, not just a reversed span."""
    with pytest.raises(ValueError, match="positive ride duration"):
        StoryBeat(
            kind=StoryBeatKind.FOOTAGE,
            ride_start_time=_at(30.0),
            ride_end_time=_at(30.0),
            screen_duration_s=5.0,
            event_id="evt_a",
        )


def test_story_beat_footage_must_carry_an_event_id_and_no_gap() -> None:
    with pytest.raises(ValueError, match="event ID and no gap"):
        StoryBeat(
            kind=StoryBeatKind.FOOTAGE,
            ride_start_time=_at(0.0),
            ride_end_time=_at(30.0),
            screen_duration_s=30.0,
            event_id=None,
        )
    with pytest.raises(ValueError, match="event ID and no gap"):
        StoryBeat(
            kind=StoryBeatKind.FOOTAGE,
            ride_start_time=_at(0.0),
            ride_end_time=_at(30.0),
            screen_duration_s=30.0,
            event_id="evt_a",
            gap=_gap(0.0, 30.0),
        )


def test_story_beat_gap_card_must_carry_a_gap_and_no_event_id() -> None:
    with pytest.raises(ValueError, match="a gap and no event ID"):
        StoryBeat(
            kind=StoryBeatKind.GAP_CARD,
            ride_start_time=_at(0.0),
            ride_end_time=_at(30.0),
            screen_duration_s=5.0,
            gap=None,
        )
    with pytest.raises(ValueError, match="a gap and no event ID"):
        StoryBeat(
            kind=StoryBeatKind.GAP_CARD,
            ride_start_time=_at(0.0),
            ride_end_time=_at(30.0),
            screen_duration_s=5.0,
            event_id="evt_a",
            gap=_gap(0.0, 30.0),
        )


def test_story_beat_ride_duration_property() -> None:
    beat = StoryBeat(
        kind=StoryBeatKind.FOOTAGE,
        ride_start_time=_at(0.0),
        ride_end_time=_at(30.0),
        screen_duration_s=30.0,
        event_id="evt_a",
    )
    assert beat.ride_duration_s == pytest.approx(30.0)


def _beat(event_id: str, start_offset_s: float, end_offset_s: float) -> StoryBeat:
    return StoryBeat(
        kind=StoryBeatKind.FOOTAGE,
        ride_start_time=_at(start_offset_s),
        ride_end_time=_at(end_offset_s),
        screen_duration_s=end_offset_s - start_offset_s,
        event_id=event_id,
    )


def test_timeline_rejects_an_empty_beat_tuple() -> None:
    with pytest.raises(ValueError, match="at least one beat"):
        StoryTimeline(())


def test_timeline_rejects_out_of_order_beats() -> None:
    with pytest.raises(ValueError, match="chronological"):
        StoryTimeline((_beat("evt_a", 100.0, 130.0), _beat("evt_b", 0.0, 30.0)))


def test_timeline_allows_beats_that_touch_exactly() -> None:
    """The overlap check is `<`: a beat starting exactly where the last one ends is fine."""
    timeline = StoryTimeline((_beat("evt_a", 0.0, 30.0), _beat("evt_b", 30.0, 60.0)))
    assert [beat.event_id for beat in timeline.beats] == ["evt_a", "evt_b"]


def test_timeline_rejects_beats_that_overlap_by_a_moment() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        StoryTimeline((_beat("evt_a", 0.0, 30.0), _beat("evt_b", 29.999, 60.0)))


def test_timeline_rejects_a_reused_event_id_constructed_directly() -> None:
    with pytest.raises(ValueError, match="reuse one event"):
        StoryTimeline((_beat("evt_a", 0.0, 30.0), _beat("evt_a", 30.0, 60.0)))


def test_gap_card_duration_rejects_negative_bounds() -> None:
    with pytest.raises(StoryTimelineError, match="bounds are invalid"):
        gap_card_screen_duration_s(_gap(0.0, 600.0), minimum_s=-1.0)
    with pytest.raises(StoryTimelineError, match="bounds are invalid"):
        gap_card_screen_duration_s(_gap(0.0, 600.0), ratio=-0.01)


def test_gap_card_duration_allows_maximum_equal_to_minimum() -> None:
    """The bound check is `maximum_s < minimum_s`: equal bounds are the allowed floor."""
    duration = gap_card_screen_duration_s(_gap(0.0, 600.0), minimum_s=5.0, maximum_s=5.0, ratio=1.0)
    assert duration == pytest.approx(5.0)


def test_gap_card_duration_clamps_exactly_at_its_bounds() -> None:
    # ratio=1/240 means a 720 s gap lands exactly on the 3 s floor, and a
    # 1920 s gap lands exactly on the 8 s ceiling; one second either side
    # of ride time must not cross the clamp.
    assert gap_card_screen_duration_s(_gap(0.0, 720.0)) == pytest.approx(3.0)
    assert gap_card_screen_duration_s(_gap(0.0, 721.0)) > 3.0
    assert gap_card_screen_duration_s(_gap(0.0, 1920.0)) == pytest.approx(8.0)
    assert gap_card_screen_duration_s(_gap(0.0, 1919.0)) < 8.0


def test_build_rejects_two_overlapping_footage_clips() -> None:
    with pytest.raises(StoryTimelineError, match="overlap"):
        build_story_timeline(
            (_footage("evt_a", 0.0, duration_s=60.0), _footage("evt_b", 30.0, duration_s=60.0)),
            JourneyGapPlan(()),
        )


def test_build_honors_custom_gap_card_bounds() -> None:
    timeline = build_story_timeline(
        (_footage("evt_a", 600.0),),
        JourneyGapPlan((_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
        minimum_gap_card_s=1.0,
        maximum_gap_card_s=2.0,
        gap_card_ratio=1.0,
    )

    gap_beat, *_ = timeline.gap_beats
    assert gap_beat.screen_duration_s == pytest.approx(2.0)
