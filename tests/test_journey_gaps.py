"""Synthetic-fixture tests for journey gap segments (Gate 2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import RoutePoint
from app.journey_gaps import (
    JourneyGapError,
    JourneyGapKind,
    JourneyGapPlan,
    JourneyGapSegment,
    build_journey_gap_plan,
)

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _points(
    count: int = 61,
    *,
    step_s: float = 60.0,
    metres_per_step: float = 500.0,
    elevation_step_m: float | None = 2.0,
) -> tuple[RoutePoint, ...]:
    return tuple(
        RoutePoint(
            timestamp=_START + timedelta(seconds=step_s * index),
            latitude=35.0 + index * 0.001,
            longitude=139.0 + index * 0.001,
            elevation_m=(None if elevation_step_m is None else 100.0 + elevation_step_m * index),
            distance_from_start_m=metres_per_step * index,
            speed_mps=metres_per_step / step_s,
        )
        for index in range(count)
    )


def _window(start_offset_s: float, end_offset_s: float) -> tuple[datetime, datetime]:
    return (
        _START + timedelta(seconds=start_offset_s),
        _START + timedelta(seconds=end_offset_s),
    )


def test_uncovered_ride_becomes_one_segment() -> None:
    plan = build_journey_gap_plan(_points(), ())

    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert segment.kind is JourneyGapKind.BEFORE_FIRST_CLIP
    assert segment.duration_s == pytest.approx(3600.0)
    assert segment.distance_m == pytest.approx(30_000.0)


def test_footage_in_the_middle_leaves_a_gap_on_each_side() -> None:
    plan = build_journey_gap_plan(_points(), (_window(1200.0, 1500.0),))

    kinds = [segment.kind for segment in plan.segments]
    assert kinds == [JourneyGapKind.BEFORE_FIRST_CLIP, JourneyGapKind.AFTER_LAST_CLIP]
    assert plan.segments[0].duration_s == pytest.approx(1200.0)
    assert plan.segments[1].duration_s == pytest.approx(2100.0)


def test_gap_between_two_covered_windows_is_reported_between_clips() -> None:
    plan = build_journey_gap_plan(
        _points(),
        (_window(0.0, 600.0), _window(1800.0, 3600.0)),
    )

    assert [segment.kind for segment in plan.segments] == [JourneyGapKind.BETWEEN_CLIPS]
    assert plan.segments[0].duration_s == pytest.approx(1200.0)


def test_fully_covered_ride_produces_no_segments() -> None:
    plan = build_journey_gap_plan(_points(), (_window(0.0, 3600.0),))

    assert plan.segments == ()
    assert plan.total_duration_s == pytest.approx(0.0)


def test_overlapping_and_unordered_windows_are_merged_before_gaps_are_taken() -> None:
    plan = build_journey_gap_plan(
        _points(),
        (_window(1800.0, 2400.0), _window(0.0, 600.0), _window(300.0, 1200.0)),
    )

    # 0-1200 and 1800-2400 are covered once merged, leaving 1200-1800 and 2400-3600.
    assert [segment.kind for segment in plan.segments] == [
        JourneyGapKind.BETWEEN_CLIPS,
        JourneyGapKind.AFTER_LAST_CLIP,
    ]
    assert plan.segments[0].duration_s == pytest.approx(600.0)
    assert plan.segments[1].duration_s == pytest.approx(1200.0)


def test_short_gap_is_left_out_rather_than_narrated() -> None:
    plan = build_journey_gap_plan(
        _points(),
        (_window(0.0, 1800.0), _window(1830.0, 3600.0)),
        minimum_gap_s=60.0,
    )

    assert plan.segments == ()


def test_elevation_gain_and_loss_are_measured_separately() -> None:
    rising = _points(count=11, elevation_step_m=5.0)
    falling = tuple(
        RoutePoint(
            timestamp=point.timestamp,
            latitude=point.latitude,
            longitude=point.longitude,
            elevation_m=200.0 - (point.distance_from_start_m / 500.0) * 3.0,
            distance_from_start_m=point.distance_from_start_m,
            speed_mps=point.speed_mps,
        )
        for point in rising
    )

    climbing = build_journey_gap_plan(rising, ()).segments[0]
    descending = build_journey_gap_plan(falling, ()).segments[0]

    assert climbing.elevation_gain_m == pytest.approx(50.0)
    assert climbing.elevation_loss_m == pytest.approx(0.0)
    assert descending.elevation_gain_m == pytest.approx(0.0)
    assert descending.elevation_loss_m == pytest.approx(30.0)


def test_track_without_elevation_reports_zero_deltas_rather_than_guessing() -> None:
    plan = build_journey_gap_plan(_points(elevation_step_m=None), ())

    assert plan.segments[0].elevation_gain_m == pytest.approx(0.0)
    assert plan.segments[0].elevation_loss_m == pytest.approx(0.0)


def test_serialized_plan_carries_aggregates_without_private_detail() -> None:
    plan = build_journey_gap_plan(_points(), (_window(1200.0, 1500.0),))

    payload = plan.to_dict()
    serialized = json.dumps(payload)

    assert payload["segment_count"] == 2
    assert set(payload["segments"][0]) == {
        "kind",
        "duration_s",
        "distance_m",
        "elevation_gain_m",
        "elevation_loss_m",
    }
    for forbidden in ("2026-05-01", "latitude", "longitude", "35.0", "139.0", "timestamp"):
        assert forbidden not in serialized


def test_too_few_points_fails_closed() -> None:
    with pytest.raises(JourneyGapError, match="at least two route points"):
        build_journey_gap_plan(_points(count=1), ())


def test_non_chronological_points_fail_closed() -> None:
    points = _points(count=3)
    reversed_points = (points[0], points[2], points[1])

    with pytest.raises(JourneyGapError, match="chronological"):
        build_journey_gap_plan(reversed_points, ())


def test_invalid_covered_window_fails_closed() -> None:
    with pytest.raises(JourneyGapError, match="positive duration"):
        build_journey_gap_plan(_points(), (_window(600.0, 600.0),))

    naive = (datetime(2026, 5, 1, 9, 0, 0), datetime(2026, 5, 1, 9, 10, 0))
    with pytest.raises(JourneyGapError, match="timezone-aware"):
        build_journey_gap_plan(_points(), (naive,))


def test_non_positive_minimum_gap_fails_closed() -> None:
    with pytest.raises(JourneyGapError, match="minimum gap"):
        build_journey_gap_plan(_points(), (), minimum_gap_s=0.0)


def test_plan_rejects_overlapping_or_unordered_segments() -> None:
    first = JourneyGapSegment(
        kind=JourneyGapKind.BEFORE_FIRST_CLIP,
        start_time=_START,
        end_time=_START + timedelta(seconds=600),
        distance_m=1000.0,
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
    )
    overlapping = JourneyGapSegment(
        kind=JourneyGapKind.BETWEEN_CLIPS,
        start_time=_START + timedelta(seconds=300),
        end_time=_START + timedelta(seconds=900),
        distance_m=1000.0,
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
    )

    with pytest.raises(ValueError, match="must not overlap"):
        JourneyGapPlan((first, overlapping))


def test_segment_rejects_a_non_positive_span() -> None:
    with pytest.raises(ValueError, match="positive duration"):
        JourneyGapSegment(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            start_time=_START,
            end_time=_START,
            distance_m=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
        )
