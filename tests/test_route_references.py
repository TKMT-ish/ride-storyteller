"""Synthetic-fixture tests for the plan/film's shared read of the reference files.

`app.route_references` has no tests of its own yet; it only reads
`app.scenic_routes` and `app.story_sections` and turns their answers into
the shapes the plan and the film both use. Nothing here touches
`private-media/`, a real GPX file, or a network call -- every reference
file is written to `tmp_path` and wired in with `monkeypatch`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import route_references
from app.contracts import RoutePoint
from app.gps.moments import MomentKind
from app.route_references import highway_runs, real_scenic, road_moments, scenic_or_none
from app.scenic_routes import TOURING_ROUTES_SCHEMA_VERSION, ScenicStretch

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_STEP_S = 10.0
# A degree of latitude is 111 km; the synthetic track runs south at 20 m/s.
_DEG_PER_M = 1.0 / 111_320.0


def _track(hours: float) -> tuple[RoutePoint, ...]:
    points: list[RoutePoint] = []
    second = 0.0
    while second <= hours * 3600.0:
        distance = 20.0 * second
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 - distance * _DEG_PER_M,
                longitude=170.0,
                elevation_m=100.0,
                distance_from_start_m=distance,
                speed_mps=20.0,
            )
        )
        second += _STEP_S
    return tuple(points)


def _route_json(tmp_path: Path, filename: str, name: str, from_s: float, to_s: float) -> Path:
    """A touring-routes-v1 file with one route lying along the track's own line."""
    line = []
    metres = 20.0 * from_s
    while metres <= 20.0 * to_s:
        line.append([-43.0 - metres * _DEG_PER_M, 170.0])
        metres += 50.0
    path = tmp_path / filename
    path.write_text(
        json.dumps(
            {
                "schema": TOURING_ROUTES_SCHEMA_VERSION,
                "routes": [{"name": name, "lines": [line]}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _stretch(route: str, start_s: float, end_s: float) -> ScenicStretch:
    return ScenicStretch(
        route=route,
        start_time=_T0 + timedelta(seconds=start_s),
        end_time=_T0 + timedelta(seconds=end_s),
    )


def _pin(monkeypatch: pytest.MonkeyPatch, paths: tuple[Path, ...]) -> None:
    """Replace `reference_files` so it hands back these paths, whatever directory is asked for."""
    monkeypatch.setattr(route_references, "reference_files", lambda directory=None: paths)


# --- scenic_or_none -----------------------------------------------------------------


def test_scenic_or_none_returns_nothing_without_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, ())
    assert scenic_or_none(_track(1.0)) == ()


def test_scenic_or_none_skips_an_unreadable_file_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _route_json(tmp_path, "good.json", "Pacific Coast Highway", 0.0, 1800.0)
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    _pin(monkeypatch, (bad, good))

    found = scenic_or_none(_track(1.0))

    assert [s.route for s in found] == ["Pacific Coast Highway"]


def test_scenic_or_none_sorts_stretches_from_several_files_by_start_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    later = _route_json(tmp_path, "later.json", "Later Loop", 2400.0, 3600.0)
    earlier = _route_json(tmp_path, "earlier.json", "Earlier Loop", 0.0, 1800.0)
    # Handed to `reference_files` in an order that does not already match time.
    _pin(monkeypatch, (later, earlier))

    found = scenic_or_none(_track(1.0))

    assert [s.route for s in found] == ["Earlier Loop", "Later Loop"]
    assert found[0].start_time < found[1].start_time


# --- highway_runs ---------------------------------------------------------------------


def test_highway_runs_returns_nothing_without_a_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, ())
    assert highway_runs(_track(1.0)) == ()


def test_highway_runs_drops_the_directional_suffix_from_the_route_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 30 minutes on the road -- well past the ten-minute floor `highway_runs` applies.
    path = _route_json(tmp_path, "sh1.json", "State Highway 1 South", 0.0, 1800.0)
    _pin(monkeypatch, (path,))

    found = highway_runs(_track(1.0))

    assert [s.route for s in found] == ["State Highway 1"]


def test_highway_runs_uses_a_ten_minute_floor_not_the_scenic_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Five minutes on the road: below `highway_runs`'s own ten-minute floor,
    # but well above `scenic_stretches`'s ordinary fifteen-minute default
    # would also reject it -- this exercises the floor `highway_runs` passes
    # explicitly, not the module-wide default.
    path = _route_json(tmp_path, "short.json", "State Highway 2", 0.0, 300.0)
    _pin(monkeypatch, (path,))

    assert highway_runs(_track(1.0)) == ()


# --- road_moments ---------------------------------------------------------------------


def test_road_moments_with_no_points_is_empty() -> None:
    assert road_moments((), ()) == ()


def test_road_moments_wraps_entries_and_exits_as_sorted_moments() -> None:
    points = _track(2.0)
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    # A run well clear of both the day's start and end, so both the join
    # and the leave are real (not the day's own setting off/pulling in).
    runs = (_stretch("State Highway 1", 1800.0, 3600.0),)

    moments = road_moments(points, runs)

    assert [m.kind for m in moments] == [MomentKind.HIGHWAY_ON, MomentKind.HIGHWAY_OFF]
    assert moments[0].at == ride_start + timedelta(seconds=1800.0)
    assert moments[1].at == _T0 + timedelta(seconds=3600.0)
    assert moments[1].at < ride_end
    assert list(moments) == sorted(moments, key=lambda m: m.at)


def test_road_moments_two_separate_runs_each_give_an_entry_and_an_exit() -> None:
    points = _track(4.0)
    runs = (
        _stretch("State Highway 1", 1800.0, 3600.0),
        _stretch("State Highway 2", 6000.0, 8000.0),
    )

    moments = road_moments(points, runs)

    kinds = [m.kind for m in moments]
    assert kinds == [
        MomentKind.HIGHWAY_ON,
        MomentKind.HIGHWAY_OFF,
        MomentKind.HIGHWAY_ON,
        MomentKind.HIGHWAY_OFF,
    ]
    assert [m.at - _T0 for m in moments] == [
        timedelta(seconds=s) for s in (1800.0, 3600.0, 6000.0, 8000.0)
    ]
    assert list(moments) == sorted(moments, key=lambda m: m.at)


# --- real_scenic ------------------------------------------------------------------------


def test_real_scenic_keeps_a_stretch_wholly_outside_every_run() -> None:
    stretches = (_stretch("Lookout Loop", 0.0, 600.0),)
    runs = (_stretch("State Highway 1", 2000.0, 4000.0),)

    assert real_scenic(stretches, runs) == stretches


def test_real_scenic_drops_a_stretch_deep_inside_a_run() -> None:
    # The run spans 0..2000s; both ends of the stretch sit at its middle,
    # far past the default 120s `edge_s` from either of the run's own ends.
    run = _stretch("State Highway 1", 0.0, 2000.0)
    stretch = _stretch("Thermal Explorer Highway", 800.0, 1200.0)

    assert real_scenic((stretch,), (run,)) == ()


def test_real_scenic_drops_when_only_one_end_is_inside_a_run() -> None:
    run = _stretch("State Highway 1", 0.0, 2000.0)
    # Starts well before the run, ends well inside it.
    stretch = _stretch("Thermal Explorer Highway", -1000.0, 1000.0)

    assert real_scenic((stretch,), (run,)) == ()


def test_real_scenic_keeps_the_edge_exactly_at_the_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _stretch("State Highway 1", 0.0, 2000.0)
    # Exactly `edge_s` inside the run's start: the check is strictly
    # between the edges, so a point sitting on the edge itself is not
    # "inside" and the stretch survives.
    stretch = _stretch("Thermal Explorer Highway", -500.0, 120.0)

    assert real_scenic((stretch,), (run,), edge_s=120.0) == (stretch,)


def test_real_scenic_drops_just_past_the_edge_threshold() -> None:
    run = _stretch("State Highway 1", 0.0, 2000.0)
    stretch = _stretch("Thermal Explorer Highway", -500.0, 121.0)

    assert real_scenic((stretch,), (run,), edge_s=120.0) == ()


def test_real_scenic_run_too_short_to_hold_an_edge_never_contains_anything() -> None:
    # A run only 100s long cannot have anything strictly between its two
    # edges once `edge_s=120` is subtracted from both ends -- the interior
    # is empty, so no end can ever be "inside" it.
    run = _stretch("State Highway 1", 0.0, 100.0)
    stretch = _stretch("Thermal Explorer Highway", -500.0, 50.0)

    assert real_scenic((stretch,), (run,), edge_s=120.0) == (stretch,)


def test_real_scenic_checks_every_run_not_only_the_first() -> None:
    first_run = _stretch("State Highway 1", 0.0, 200.0)
    second_run = _stretch("State Highway 29", 2000.0, 4000.0)
    # Clear of the first run, well inside the second.
    stretch = _stretch("Thermal Explorer Highway", 2500.0, 3000.0)

    assert real_scenic((stretch,), (first_run, second_run)) == ()
