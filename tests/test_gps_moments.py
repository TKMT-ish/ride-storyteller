"""Synthetic-track tests for the moments a day's track proves."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import RoutePoint
from app.gps.moments import (
    ROLLING_MPS,
    SUSTAINED_M,
    SUSTAINED_S,
    Moment,
    MomentKind,
    _moved,
    _pace,
    come_to_rest,
    day_moments,
    set_off,
)
from app.ride_chapters import long_halts

_T0 = datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)
_STEP_S = 10.0


def _points(steps: tuple[tuple[float, float], ...]) -> tuple[RoutePoint, ...]:
    """Build points directly from (offset_seconds, distance_m) pairs."""
    return tuple(
        RoutePoint(
            timestamp=_T0 + timedelta(seconds=offset),
            latitude=-43.0 + distance / 111_000.0,
            longitude=170.0,
            elevation_m=100.0,
            distance_from_start_m=distance,
            speed_mps=None,
        )
        for offset, distance in steps
    )


def _track(
    *, still_before_s: float, riding_s: float, halt: tuple[float, float] | None = None
) -> tuple[RoutePoint, ...]:
    """Standing still, then riding at 20 m/s (with an optional halt), then standing still."""
    points: list[RoutePoint] = []
    distance = 0.0
    second = 0.0
    end = still_before_s + riding_s + 300.0
    while second <= end:
        moving = still_before_s <= second < still_before_s + riding_s
        if halt and halt[0] <= second <= halt[1]:
            moving = False
        if points and moving:
            distance += 20.0 * _STEP_S
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 + distance / 111_000.0,
                longitude=170.0,
                elevation_m=100.0,
                distance_from_start_m=distance,
                speed_mps=20.0 if moving else 0.0,
            )
        )
        second += _STEP_S
    return tuple(points)


def test_setting_off_is_when_the_ride_first_gets_under_way() -> None:
    track = _track(still_before_s=600.0, riding_s=3600.0)

    began = set_off(track)

    assert began is not None
    assert abs((began - (_T0 + timedelta(seconds=600))).total_seconds()) <= _STEP_S


def test_coming_to_rest_is_when_the_ride_last_stopped() -> None:
    track = _track(still_before_s=600.0, riding_s=3600.0)

    ended = come_to_rest(track)

    assert ended is not None
    assert abs((ended - (_T0 + timedelta(seconds=4200))).total_seconds()) <= _STEP_S


def test_a_track_that_never_moves_has_no_moments() -> None:
    track = _track(still_before_s=1200.0, riding_s=0.0)

    assert set_off(track) is None
    assert come_to_rest(track) is None
    assert day_moments(track, ()) == ()


def test_a_day_with_one_halt_has_four_moments_in_ride_order() -> None:
    halt = (2 * 3600.0, 2 * 3600.0 + 25 * 60.0)
    track = _track(still_before_s=300.0, riding_s=4 * 3600.0, halt=halt)

    moments = day_moments(track, long_halts(track))

    assert [m.kind for m in moments] == [
        MomentKind.DEPARTURE,
        MomentKind.HALT_ARRIVAL,
        MomentKind.HALT_DEPARTURE,
        MomentKind.ARRIVAL,
    ]
    assert [m.at for m in moments] == sorted(m.at for m in moments)
    assert moments[1].halt == 0 and moments[2].halt == 0
    stood = (moments[2].at - moments[1].at).total_seconds()
    assert 24 * 60 <= stood <= 26 * 60


def test_a_halt_outside_the_ride_is_not_a_moment() -> None:
    """A halt the caller names before the ride began is not part of the day."""
    track = _track(still_before_s=300.0, riding_s=3600.0)
    before = (_T0 - timedelta(hours=1), _T0 - timedelta(minutes=30))

    moments = day_moments(track, (before,))

    assert [m.kind for m in moments] == [MomentKind.DEPARTURE, MomentKind.ARRIVAL]


def test_a_moment_names_its_halt_only_when_it_is_one() -> None:
    with pytest.raises(ValueError):
        Moment(MomentKind.DEPARTURE, _T0, halt=0)
    with pytest.raises(ValueError):
        Moment(MomentKind.HALT_ARRIVAL, _T0)
    with pytest.raises(ValueError):
        Moment(MomentKind.ARRIVAL, _T0.replace(tzinfo=None))


def test_a_moment_rejects_a_naive_clock_even_when_its_halt_is_otherwise_correct() -> None:
    """Isolates the timezone check from the halt-naming check above it."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Moment(MomentKind.ARRIVAL, _T0.replace(tzinfo=None))


def test_moved_and_pace_treat_a_repeated_timestamp_as_stationary_only_without_distance() -> None:
    """`_moved`/`_pace` divide by elapsed time; a duplicate timestamp must not raise."""
    jumped = _points(((0.0, 0.0), (0.0, 50.0)))
    assert _moved(jumped, 1) is True
    assert _pace(jumped, 1) == 0.0

    held = _points(((0.0, 50.0), (0.0, 50.0)))
    assert _moved(held, 1) is False
    assert _pace(held, 1) == 0.0


def test_moved_treats_out_of_order_timestamps_as_stationary_for_the_pace_clamp() -> None:
    """A negative elapsed (points out of ride order) clamps to 0 rather than negating the gap."""
    reversed_order = _points(((10.0, 0.0), (0.0, 50.0)))
    assert _moved(reversed_order, 1) is True
    assert _pace(reversed_order, 1) == 0.0


def test_moved_is_false_exactly_at_the_walking_pace_boundary() -> None:
    """1.5 m/s over 10 s is 15 m: the boundary itself is walking, not riding (strict `>`)."""
    at_boundary = _points(((0.0, 0.0), (10.0, 15.0)))
    just_over = _points(((0.0, 0.0), (10.0, 15.0001)))
    assert _moved(at_boundary, 1) is False
    assert _moved(just_over, 1) is True


def test_set_off_and_come_to_rest_are_none_on_a_track_too_short_to_move() -> None:
    assert set_off(()) is None
    assert set_off(_points(((0.0, 0.0),))) is None
    assert come_to_rest(()) is None
    assert come_to_rest(_points(((0.0, 0.0),))) is None


def test_set_off_boundary_is_inclusive_at_exactly_the_sustained_distance() -> None:
    """Exactly SUSTAINED_M in SUSTAINED_S counts (`>=`); a metre short does not."""
    assert SUSTAINED_M == 300.0 and SUSTAINED_S == 60.0
    exactly = _points(((0.0, 0.0), (60.0, 300.0)))
    short = _points(((0.0, 0.0), (60.0, 299.0)))
    assert set_off(exactly) == _T0
    assert set_off(short) is None


def test_come_to_rest_boundary_is_inclusive_at_exactly_the_sustained_distance() -> None:
    exactly = _points(((0.0, 0.0), (60.0, 300.0)))
    short = _points(((0.0, 0.0), (60.0, 299.0)))
    assert come_to_rest(exactly) == _T0 + timedelta(seconds=60)
    assert come_to_rest(short) is None


def test_set_off_scans_past_a_false_start_that_never_sustains() -> None:
    """A blip that clears the walking threshold but stalls short of SUSTAINED_M must not
    be mistaken for the departure; the scan keeps going to the ride that actually holds."""
    steps: list[tuple[float, float]] = [(0.0, 0.0), (10.0, 20.0)]  # blip: 20 m in 10 s
    offset, distance = 20.0, 20.0
    while offset <= 590.0:  # plateau -- no further movement for a while
        steps.append((offset, distance))
        offset += 10.0
    offset = 600.0
    while offset <= 700.0:  # then a real, sustained ride at 5 m/s
        distance += 50.0
        steps.append((offset, distance))
        offset += 10.0

    began = set_off(_points(tuple(steps)))

    assert began is not None
    # the real roll-off is at t=600s; the false blip at t=10s must not be returned.
    assert abs((began - (_T0 + timedelta(seconds=600))).total_seconds()) <= _STEP_S


def test_set_off_refinement_stops_exactly_at_the_rolling_pace_boundary() -> None:
    """Within a sustained window, the creep before the roll-off is skipped only while its
    pace is strictly under ROLLING_MPS; a step at exactly ROLLING_MPS ends the refinement."""
    assert ROLLING_MPS == 2.5
    track = _points(
        (
            (0.0, 0.0),
            (10.0, 20.0),  # creep at 2.0 m/s -- refined past
            (20.0, 45.0),  # exactly 2.5 m/s -- refinement stops here
            (30.0, 110.0),
            (40.0, 175.0),
            (50.0, 240.0),
            (60.0, 300.0),  # sustained total is exactly the SUSTAINED_M boundary
        )
    )

    began = set_off(track)

    assert began == _T0 + timedelta(seconds=10)


def test_day_moments_numbers_halts_by_ride_order_not_the_order_given() -> None:
    halt = (2 * 3600.0, 2 * 3600.0 + 25 * 60.0)
    earlier_halt = (1000.0, 1200.0)
    track = _track(still_before_s=300.0, riding_s=4 * 3600.0, halt=halt)
    earlier = (
        _T0 + timedelta(seconds=earlier_halt[0]),
        _T0 + timedelta(seconds=earlier_halt[1]),
    )
    later = (_T0 + timedelta(seconds=halt[0]), _T0 + timedelta(seconds=halt[1]))

    # passed out of ride order: the later halt first, the earlier halt second.
    moments = day_moments(track, (later, earlier))

    arrivals = [m for m in moments if m.kind is MomentKind.HALT_ARRIVAL]
    assert [a.at for a in arrivals] == sorted(a.at for a in arrivals)
    assert arrivals[0].at == earlier[0] and arrivals[0].halt == 0
    assert arrivals[1].at == later[0] and arrivals[1].halt == 1


def test_day_moments_drops_a_halt_straddling_departure_or_arrival() -> None:
    """`start <= began or end >= ended` -- a halt need only straddle one edge to be dropped,
    not fall entirely outside the ride."""
    track = _track(still_before_s=300.0, riding_s=3600.0)
    began = set_off(track)
    ended = come_to_rest(track)
    assert began is not None and ended is not None
    straddles_departure = (began - timedelta(seconds=100), began + timedelta(seconds=100))
    straddles_arrival = (ended - timedelta(seconds=100), ended + timedelta(seconds=100))

    at_start = day_moments(track, (straddles_departure,))
    at_end = day_moments(track, (straddles_arrival,))

    assert [m.kind for m in at_start] == [MomentKind.DEPARTURE, MomentKind.ARRIVAL]
    assert [m.kind for m in at_end] == [MomentKind.DEPARTURE, MomentKind.ARRIVAL]
