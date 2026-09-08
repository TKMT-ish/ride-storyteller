"""Synthetic-fixture tests for reading a ferry crossing off the track and the camera."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import RoutePoint
from app.ferries import (
    FerriesError,
    FerryCrossing,
    afloat,
    crossing_at,
    crossing_distance_m,
    ferries_or_none,
    ferry_crossings,
)
from app.scenic_routes import TOURING_ROUTES_SCHEMA_VERSION, TouringRoute

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_DEG_PER_M = 1.0 / 111_320.0
_STEP_S = 10.0


def _track(*legs: tuple[float, float]) -> tuple[RoutePoint, ...]:
    """A track running due north; each leg is (seconds, metres a second)."""
    points: list[RoutePoint] = []
    second = 0.0
    metres = 0.0
    for duration, mps in legs:
        end = second + duration
        while second <= end:
            points.append(
                RoutePoint(
                    timestamp=_T0 + timedelta(seconds=second),
                    latitude=metres * _DEG_PER_M,
                    longitude=0.0,
                    elevation_m=0.0,
                    distance_from_start_m=metres,
                    speed_mps=mps,
                )
            )
            second += _STEP_S
            metres += mps * _STEP_S
    return tuple(points)


def _line(points: tuple[RoutePoint, ...]) -> TouringRoute:
    """A charted line lying exactly along the given part of the track."""
    return TouringRoute(
        name="Harbour - Far Shore (Line)",
        lines=((tuple((p.latitude, p.longitude) for p in points),),)[0],
    )


def _witnesses(points: tuple[RoutePoint, ...], *at_s: float) -> tuple[datetime, ...]:
    return tuple(_T0 + timedelta(seconds=s) for s in at_s)


# --- the reference ------------------------------------------------------------


def test_a_reference_of_another_version_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text(json.dumps({"schema": "other"}), encoding="utf-8")

    assert ferries_or_none(tmp_path) == ()


def test_the_ferry_lines_are_read_from_the_directory(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text(
        json.dumps(
            {
                "schema": TOURING_ROUTES_SCHEMA_VERSION,
                "routes": [{"name": "A - B", "lines": [[[0.0, 0.0], [0.1, 0.0]]]}],
            }
        ),
        encoding="utf-8",
    )

    assert [r.name for r in ferries_or_none(tmp_path)] == ["A - B"]


# --- a crossing ----------------------------------------------------------------


def test_a_crossing_is_claimed_when_the_line_the_pace_and_the_camera_agree() -> None:
    points = _track((3600.0, 9.0))  # an hour at a ship's pace, 32 km
    crossings = ferry_crossings(
        points,
        (_line(points),),
        witnessed=_witnesses(points, 60.0),
        aboard=_witnesses(points, 120.0),
    )

    assert len(crossings) == 1
    assert crossings[0].duration_s >= 3000.0


def test_without_a_sight_of_the_deck_a_shore_road_is_only_a_road() -> None:
    """A shore road followed a charted line for an hour and a half; a town's
    main street with a sign to the terminal did the same."""
    points = _track((3600.0, 9.0))

    assert ferry_crossings(points, (_line(points),), witnessed=_witnesses(points, 60.0)) == ()
    assert ferry_crossings(points, (_line(points),)) == ()


def test_a_road_ride_is_too_fast_to_be_a_ship() -> None:
    points = _track((3600.0, 25.0))  # 90 km/h for an hour

    crossings = ferry_crossings(
        points,
        (_line(points),),
        witnessed=_witnesses(points, 60.0),
        aboard=_witnesses(points, 120.0),
    )

    assert crossings == ()


def test_a_short_hop_is_not_a_crossing() -> None:
    points = _track((600.0, 9.0))  # ten minutes, 5.4 km

    crossings = ferry_crossings(
        points,
        (_line(points),),
        witnessed=_witnesses(points, 60.0),
        aboard=_witnesses(points, 120.0),
    )

    assert crossings == ()


def test_the_crossing_begins_where_the_ride_queued() -> None:
    """The wait at the terminal is part of taking the ferry; the road that got
    there is not."""
    points = _track((3600.0, 9.0))
    queue = (_T0 + timedelta(seconds=300), _T0 + timedelta(seconds=900))

    crossings = ferry_crossings(
        points,
        (_line(points),),
        witnessed=_witnesses(points, 600.0),
        aboard=_witnesses(points, 1200.0),
        halts=(queue,),
    )

    assert len(crossings) == 1
    assert crossings[0].start_time == queue[0]


def test_a_ships_pace_must_be_positive() -> None:
    with pytest.raises(FerriesError):
        ferry_crossings(_track((60.0, 1.0)), (), ship_max_mps=0.0)


# --- what a crossing means afterwards -------------------------------------------


def test_a_crossing_must_cover_a_positive_duration() -> None:
    with pytest.raises(FerriesError):
        FerryCrossing(name="A - B", start_time=_T0, end_time=_T0)


def test_the_hours_afloat_are_not_kilometres_ridden() -> None:
    points = _track((3600.0, 9.0))
    crossing = FerryCrossing(name="A - B", start_time=_T0, end_time=_T0 + timedelta(seconds=3600.0))

    assert crossing_distance_m(points, (crossing,)) > 30_000.0
    assert crossing_distance_m(points, ()) == 0.0


def test_being_afloat_is_asked_with_a_little_slack() -> None:
    crossing = FerryCrossing(name="A - B", start_time=_T0, end_time=_T0 + timedelta(seconds=3600.0))
    just_after = _T0 + timedelta(seconds=3700.0)

    assert afloat((crossing,), _T0 + timedelta(seconds=10.0)) is True
    assert afloat((crossing,), just_after) is False
    assert afloat((crossing,), just_after, slack_s=300.0) is True
    assert crossing_at((crossing,), just_after) is None
    assert crossing_at((crossing,), _T0 + timedelta(seconds=10.0)) is crossing
