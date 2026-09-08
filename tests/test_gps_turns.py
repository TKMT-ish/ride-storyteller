"""Synthetic-track tests for sharp turns read off the GPS (Q1).

Held: a corner taken at riding speed is one turn with the right sign;
a gentle bend is not; a swing made while stopping is not; and GPS jitter
at a standstill produces nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import RoutePoint
from app.gps.turns import SharpTurn, SharpTurnError, _bearing, _turned, sharp_turns

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_STEP_DEG = 0.0001  # about 11 m per second of northing at 40 m/s... kept simple


def _point(second: int, lat: float, lon: float, speed: float = 12.0) -> RoutePoint:
    return RoutePoint(
        timestamp=_T0 + timedelta(seconds=second),
        latitude=lat,
        longitude=lon,
        elevation_m=100.0,
        distance_from_start_m=12.0 * second,
        speed_mps=speed,
    )


def _leg(
    start_second: int, lat: float, lon: float, *, north: float, east: float, count: int, speed=12.0
):
    """`count` points moving by (north, east) degrees each second."""
    points = []
    for i in range(count):
        points.append(_point(start_second + i, lat + north * i, lon + east * i, speed))
    return points


def _corner(*, right: bool, speed: float = 12.0) -> tuple[RoutePoint, ...]:
    """North for 30 s, then a heading of 120 degrees (right) or 240 (left) for 30 s."""
    first = _leg(0, 35.0, 139.0, north=_STEP_DEG, east=0.0, count=30, speed=speed)
    last = first[-1]
    east = (_STEP_DEG if right else -_STEP_DEG) * 0.866
    second = _leg(
        30, last.latitude, last.longitude, north=-_STEP_DEG * 0.5, east=east, count=30, speed=speed
    )
    return tuple(first + second)


def test_a_right_angle_corner_at_speed_is_one_right_turn() -> None:
    turns = sharp_turns(_corner(right=True))

    assert len(turns) == 1
    assert turns[0].is_right and 110.0 <= turns[0].degrees <= 130.0
    assert _T0 + timedelta(seconds=20) <= turns[0].middle <= _T0 + timedelta(seconds=40)


def test_a_left_corner_is_negative() -> None:
    (turn,) = sharp_turns(_corner(right=False))

    assert not turn.is_right and -130.0 <= turn.degrees <= -110.0


def test_a_gentle_bend_is_not_a_turn() -> None:
    # Heading drifts 1 degree a second: 10 degrees in any 10 s span.
    import math

    points = []
    lat, lon = 35.0, 139.0
    for second in range(120):
        heading = math.radians(second * 1.0)
        points.append(_point(second, lat, lon))
        lat += _STEP_DEG * math.cos(heading)
        lon += _STEP_DEG * math.sin(heading)

    assert sharp_turns(tuple(points)) == ()


def test_a_turn_made_while_stopping_is_not_a_turn() -> None:
    slow = _corner(right=True, speed=1.0)

    assert sharp_turns(slow) == ()


def test_jitter_at_a_standstill_is_nothing() -> None:
    points = []
    for second in range(60):
        wobble = 0.00001 if second % 2 else -0.00001
        points.append(_point(second, 35.0 + wobble, 139.0 - wobble, speed=0.0))

    assert sharp_turns(tuple(points)) == ()


def test_two_corners_are_two_turns_and_the_search_resumes_after_each() -> None:
    first = _corner(right=True)
    last = first[-1]
    # After heading 120 degrees, turn north again: a left turn.
    third = _leg(60, last.latitude, last.longitude, north=_STEP_DEG, east=0.0, count=30)
    turns = sharp_turns(tuple(first) + tuple(third))

    assert [t.is_right for t in turns] == [True, False]


def test_thresholds_must_be_positive_and_a_turn_must_swing() -> None:
    with pytest.raises(SharpTurnError):
        sharp_turns(_corner(right=True), min_degrees=0)
    with pytest.raises(ValueError, match="swings"):
        SharpTurn(_T0, _T0 + timedelta(seconds=5), 0.0)
    with pytest.raises(ValueError, match="take some time"):
        SharpTurn(_T0, _T0, 90.0)


def test_span_s_and_min_speed_have_their_own_rejections() -> None:
    # min_degrees=0 above already covers that branch; span_s and a negative
    # min_speed_mps are the other two disjuncts of the same guard, each
    # untested on its own until now.
    with pytest.raises(SharpTurnError):
        sharp_turns(_corner(right=True), span_s=0)
    with pytest.raises(SharpTurnError):
        sharp_turns(_corner(right=True), span_s=-1)
    with pytest.raises(SharpTurnError):
        sharp_turns(_corner(right=True), min_speed_mps=-1)


def test_min_speed_mps_of_zero_is_accepted_not_rejected() -> None:
    # The guard is `min_speed_mps < 0`: zero is the boundary that must still
    # pass (a rider stopped dead is not itself an invalid threshold).
    turns = sharp_turns(_corner(right=True), min_speed_mps=0)

    assert len(turns) == 1


def test_fewer_than_three_points_is_empty_not_an_error() -> None:
    # The scan condition is `index < count - 2`; for count in {0, 1, 2} that
    # is never true, so the loop body -- and any indexing into it -- never
    # runs.
    for count in (0, 1, 2):
        points = tuple(_point(i, 35.0 + i * _STEP_DEG, 139.0) for i in range(count))
        assert sharp_turns(points) == ()


def test_a_missing_speed_reading_is_treated_as_stationary() -> None:
    # RoutePoint.speed_mps is optional; `(speed_mps or 0.0)` folds None to
    # zero, which is below every positive min_speed_mps and so halts a scan
    # the same way an explicit low speed does.
    points = tuple(
        _point(i, 35.0 + i * _STEP_DEG, 139.0 + i * _STEP_DEG, speed=None) for i in range(10)
    )

    assert sharp_turns(points) == ()


def test_bearing_of_the_four_cardinal_directions() -> None:
    # `_bearing` is 0=north, 90=east, 180=south, 270=west; each derived
    # independently below rather than from `_STEP_DEG`'s already-tested
    # corner geometry.
    origin = _point(0, 35.0, 139.0)
    assert _bearing(origin, _point(1, 35.001, 139.0)) == pytest.approx(0.0, abs=1e-6)
    assert _bearing(origin, _point(1, 35.0, 139.001)) == pytest.approx(90.0, abs=1e-3)
    assert _bearing(origin, _point(1, 34.999, 139.0)) == pytest.approx(180.0, abs=1e-6)
    assert _bearing(origin, _point(1, 35.0, 138.999)) == pytest.approx(270.0, abs=1e-3)


def test_turned_wraps_across_the_zero_boundary_both_ways() -> None:
    # A heading crossing 360/0 must read as a small turn, not a ~340 degree
    # one, in either direction.
    assert _turned(350.0, 10.0) == pytest.approx(20.0)
    assert _turned(10.0, 350.0) == pytest.approx(-20.0)


def test_turned_at_a_dead_u_turn_lands_on_negative_180_not_positive() -> None:
    # The docstring promises [-180, 180): a swing of exactly 180 degrees
    # (either way, since the two are indistinguishable mod 360) resolves to
    # -180.0, and +180.0 itself is never produced -- confirmed by closing
    # in on it from below without ever reaching it.
    assert _turned(0.0, 180.0) == -180.0
    assert _turned(0.0, 179.999999) == pytest.approx(179.999999)


def test_a_turn_writes_only_aggregates() -> None:
    (turn,) = sharp_turns(_corner(right=True))

    written = turn.to_dict()
    assert set(written) == {"duration_s", "degrees"}


def test_to_dict_rounds_duration_to_millis_and_degrees_to_tenths() -> None:
    turn = SharpTurn(_T0, _T0 + timedelta(seconds=1, milliseconds=500), 123.456)

    assert turn.to_dict() == {"duration_s": 1.5, "degrees": 123.5}


def test_middle_is_the_exact_midpoint_not_just_within_bounds() -> None:
    turn = SharpTurn(_T0, _T0 + timedelta(seconds=7), 90.0)

    assert turn.middle == _T0 + timedelta(seconds=3, milliseconds=500)
