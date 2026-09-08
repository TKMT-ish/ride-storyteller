"""Synthetic-fixture tests for matching a day's track to official scenic routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import RoutePoint
from app.scenic_routes import (
    MERGE_UNDER_M,
    TOURING_ROUTES_SCHEMA_VERSION,
    ScenicRoutesError,
    ScenicStretch,
    TouringRoute,
    _cell,
    _distance_m,
    _RouteIndex,
    load_touring_routes,
    reference_files,
    scenic_stretches,
    stretch_at,
    stretches_within,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_STEP_S = 10.0
# A degree of latitude is 111 km; the track runs south at 20 m/s.
_DEG_PER_M = 1.0 / 111_320.0


def _track(hours: float, *, offset_east_m: float = 0.0) -> tuple[RoutePoint, ...]:
    points: list[RoutePoint] = []
    second = 0.0
    while second <= hours * 3600.0:
        distance = 20.0 * second
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 - distance * _DEG_PER_M,
                longitude=170.0 + offset_east_m * _DEG_PER_M / 0.7314,
                elevation_m=100.0,
                distance_from_start_m=distance,
                speed_mps=20.0,
            )
        )
        second += _STEP_S
    return tuple(points)


def _route(name: str, from_s: float, to_s: float, *, offset_east_m: float = 0.0) -> TouringRoute:
    """A route lying along the track between two ride seconds, every 50 m."""
    line = []
    metres = 20.0 * from_s
    while metres <= 20.0 * to_s:
        line.append((-43.0 - metres * _DEG_PER_M, 170.0 + offset_east_m * _DEG_PER_M / 0.7314))
        metres += 50.0
    return TouringRoute(name=name, lines=(tuple(line),))


def test_a_run_along_a_route_is_a_stretch_with_the_routes_name() -> None:
    track = _track(3)
    route = _route("Southern Scenic Route", 3600.0, 7200.0)

    found = scenic_stretches(track, (route,))

    assert len(found) == 1
    assert found[0].route == "Southern Scenic Route"
    assert abs((found[0].start_time - (_T0 + timedelta(hours=1))).total_seconds()) <= 30
    assert abs((found[0].end_time - (_T0 + timedelta(hours=2))).total_seconds()) <= 30


def test_a_road_beside_the_route_is_not_on_it() -> None:
    track = _track(3, offset_east_m=400.0)

    assert scenic_stretches(track, (_route("Beside", 0.0, 10_800.0),)) == ()


def test_a_short_brush_with_a_route_is_not_a_chapter() -> None:
    track = _track(3)

    assert scenic_stretches(track, (_route("Brief", 3600.0, 3600.0 + 5 * 60.0),)) == ()


def test_a_short_detour_off_the_route_does_not_split_the_stretch() -> None:
    track = _track(3)
    on_again = TouringRoute(
        name="Gapped",
        lines=(_route("a", 3600.0, 5000.0).lines[0], _route("b", 5100.0, 7200.0).lines[0]),
    )

    found = scenic_stretches(track, (on_again,))

    assert len(found) == 1
    assert found[0].duration_s >= 3500.0


def test_two_routes_sharing_a_road_do_not_overlap_the_longer_wins() -> None:
    track = _track(4)
    long = _route("Long", 3600.0, 12_000.0)
    short = _route("Short", 5000.0, 7000.0)

    found = scenic_stretches(track, (short, long))

    assert [s.route for s in found] == ["Long"]


def test_stretches_are_found_and_clipped_by_time() -> None:
    stretch = ScenicStretch("R", _T0 + timedelta(hours=1), _T0 + timedelta(hours=2))

    assert stretch_at((stretch,), _T0 + timedelta(hours=1, minutes=30)) is stretch
    assert stretch_at((stretch,), _T0 + timedelta(hours=3)) is None
    clipped = stretches_within((stretch,), _T0 + timedelta(minutes=90), _T0 + timedelta(hours=5))
    assert clipped[0].start_time == _T0 + timedelta(minutes=90)
    assert clipped[0].end_time == stretch.end_time


def test_the_reference_file_is_read_and_refused_when_wrong(tmp_path: Path) -> None:
    good = tmp_path / "nz.json"
    good.write_text(
        json.dumps(
            {
                "schema": TOURING_ROUTES_SCHEMA_VERSION,
                "routes": [{"name": "R", "lines": [[[-43.0, 170.0], [-43.1, 170.0]]]}],
            }
        ),
        encoding="utf-8",
    )
    assert load_touring_routes(good)[0].name == "R"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other", "routes": []}), encoding="utf-8")
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(bad)
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(tmp_path / "missing.json")


def test_reference_files_come_from_the_directory_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("RIDE_TOURING_ROUTES", raising=False)

    assert [p.name for p in reference_files(tmp_path)] == ["a.json", "b.json"]
    assert reference_files(tmp_path / "nowhere") == ()

    monkeypatch.setenv("RIDE_TOURING_ROUTES", str(tmp_path / "b.json"))
    assert reference_files(tmp_path) == (tmp_path / "b.json",)


def test_nonsense_thresholds_are_refused() -> None:
    with pytest.raises(ScenicRoutesError):
        scenic_stretches(_track(1), (), on_route_m=0.0)
    with pytest.raises(ScenicRoutesError):
        scenic_stretches(_track(1), (), on_route_m=-1.0)
    with pytest.raises(ScenicRoutesError):
        scenic_stretches(_track(1), (), minimum_s=0.0)
    with pytest.raises(ScenicRoutesError):
        scenic_stretches(_track(1), (), minimum_s=-1.0)
    with pytest.raises(ScenicRoutesError):
        scenic_stretches(_track(1), (), max_gap_s=-1.0)
    # max_gap_s=0.0 is the permitted lower edge itself (rejection is `< 0`, not `<= 0`).
    assert scenic_stretches(_track(1), (), max_gap_s=0.0) == ()


def test_touring_route_requires_a_name_and_at_least_one_point() -> None:
    with pytest.raises(ScenicRoutesError):
        TouringRoute(name="  ", lines=(((-43.0, 170.0),),))
    with pytest.raises(ScenicRoutesError):
        TouringRoute(name="R", lines=())
    with pytest.raises(ScenicRoutesError):
        TouringRoute(name="R", lines=((),))
    # A route made only of empty lines is the same as no lines at all.
    with pytest.raises(ScenicRoutesError):
        TouringRoute(name="R", lines=((), ()))


def test_scenic_stretch_requires_a_positive_duration() -> None:
    with pytest.raises(ScenicRoutesError):
        ScenicStretch(route="R", start_time=_T0, end_time=_T0)
    with pytest.raises(ScenicRoutesError):
        ScenicStretch(route="R", start_time=_T0, end_time=_T0 - timedelta(seconds=1))
    # One second is the minimum positive duration accepted.
    stretch = ScenicStretch(route="R", start_time=_T0, end_time=_T0 + timedelta(seconds=1))
    assert stretch.duration_s == 1.0


def test_load_touring_routes_rejects_malformed_shapes(tmp_path: Path) -> None:
    def written(payload: object) -> Path:
        path = tmp_path / "malformed.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    with pytest.raises(ScenicRoutesError):
        load_touring_routes(written(["not", "a", "dict"]))
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(
            written({"schema": TOURING_ROUTES_SCHEMA_VERSION, "routes": ["not a dict"]})
        )
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(
            written({"schema": TOURING_ROUTES_SCHEMA_VERSION, "routes": [{"name": 1, "lines": []}]})
        )
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(
            written(
                {
                    "schema": TOURING_ROUTES_SCHEMA_VERSION,
                    "routes": [{"name": "R", "lines": "not a list"}],
                }
            )
        )
    with pytest.raises(ScenicRoutesError):
        load_touring_routes(
            written(
                {
                    "schema": TOURING_ROUTES_SCHEMA_VERSION,
                    "routes": [{"name": "R", "lines": [[["not", "a", "number"]]]}],
                }
            )
        )


def test_stretch_at_boundary_is_half_open() -> None:
    stretch = ScenicStretch("R", _T0, _T0 + timedelta(hours=1))

    assert stretch_at((stretch,), stretch.start_time) is stretch
    assert stretch_at((stretch,), stretch.end_time - timedelta(microseconds=1)) is stretch
    # The end instant belongs to whatever comes after, not to this stretch.
    assert stretch_at((stretch,), stretch.end_time) is None
    assert stretch_at((stretch,), stretch.start_time - timedelta(microseconds=1)) is None


def test_stretches_within_excludes_a_span_touching_only_at_the_edge() -> None:
    stretch = ScenicStretch("R", _T0 + timedelta(hours=1), _T0 + timedelta(hours=2))

    # A query span ending exactly where the stretch starts shares no time with it.
    assert stretches_within((stretch,), _T0, stretch.start_time) == ()
    assert stretches_within((stretch,), stretch.end_time, _T0 + timedelta(hours=5)) == ()
    # One instant of overlap is enough to be included, clipped to that instant's edge.
    touching = stretches_within(
        (stretch,),
        stretch.start_time - timedelta(seconds=1),
        stretch.start_time + timedelta(seconds=1),
    )
    assert touching[0].start_time == stretch.start_time
    assert touching[0].end_time == stretch.start_time + timedelta(seconds=1)


def test_route_index_near_is_inclusive_at_the_measured_distance() -> None:
    """`near` accepts a point exactly `radius_m` away (`<=`), not only strictly closer."""
    route = TouringRoute(name="R", lines=(((0.0, 0.0),),))
    index = _RouteIndex(route)
    lon = 0.001  # about 111 m east of the route's point at the equator
    exact = _distance_m(0.0, 0.0, 0.0, lon)

    assert index.near(0.0, lon, exact) is True
    assert index.near(0.0, lon, exact - 1e-9) is False


def test_cell_assigns_by_floor_not_by_rounding() -> None:
    assert _cell(0.0099, 0.0) == (0, 0)
    assert _cell(0.01, 0.0) == (1, 0)
    assert _cell(-0.0001, 0.0) == (-1, 0)
    assert _cell(-0.01, 0.0) == (-1, 0)


def _closed_runs_track(*, gap_advance_m: float, max_gap_s: float) -> tuple[RoutePoint, ...]:
    """Two on-route runs separated by an off-route gap that advances `gap_advance_m`.

    The gap is longer than `max_gap_s`, so the two runs close separately before
    `_joined_across_halts` decides whether to merge them by distance advanced.
    """
    points: list[RoutePoint] = []
    # Run 1: on-route (same corridor as `_track`/`_route`), 0..100s.
    for second in range(0, 101, 10):
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
    last_distance = points[-1].distance_from_start_m
    gap_start = 110.0
    gap_end = gap_start + max_gap_s + 10.0
    gap_seconds = [gap_start, (gap_start + gap_end) / 2.0, gap_end]
    for i, second in enumerate(gap_seconds):
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=points[-1].latitude,
                longitude=171.0,  # far enough east to be off every route below
                elevation_m=100.0,
                distance_from_start_m=last_distance + gap_advance_m * (i + 1) / len(gap_seconds),
                speed_mps=20.0,
            )
        )
    # Run 2: back on-route, another 100s, continuing the same corridor.
    resume_second = gap_end + 10.0
    resume_distance = last_distance + gap_advance_m
    for second in range(0, 101, 10):
        distance = resume_distance + 20.0 * second
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=resume_second + second),
                latitude=-43.0 - distance * _DEG_PER_M,
                longitude=170.0,
                elevation_m=100.0,
                distance_from_start_m=distance,
                speed_mps=20.0,
            )
        )
    return tuple(points)


def test_runs_advanced_exactly_merge_under_m_apart_do_not_merge() -> None:
    """`MERGE_UNDER_M` is a strict `<`, so exactly at the threshold stays two stretches."""
    track = _closed_runs_track(gap_advance_m=MERGE_UNDER_M, max_gap_s=30.0)
    route = TouringRoute(name="R", lines=(_route("r", 0.0, 500.0).lines[0],))

    found = scenic_stretches(track, (route,), max_gap_s=30.0, minimum_s=10.0)

    assert len(found) == 2


def test_runs_advanced_just_under_merge_under_m_do_merge() -> None:
    track = _closed_runs_track(gap_advance_m=MERGE_UNDER_M - 1.0, max_gap_s=30.0)
    route = TouringRoute(name="R", lines=(_route("r", 0.0, 500.0).lines[0],))

    found = scenic_stretches(track, (route,), max_gap_s=30.0, minimum_s=10.0)

    assert len(found) == 1
    assert found[0].start_time == track[0].timestamp
    assert found[0].end_time == track[-1].timestamp


def test_equal_duration_overlap_keeps_the_earlier_starting_stretch() -> None:
    track = _track(4)
    first = _route("First", 3600.0, 5400.0)
    second = _route("Second", 4500.0, 6300.0)

    found = scenic_stretches(track, (second, first))

    assert [s.route for s in found] == ["First"]


def test_a_halt_inside_a_route_does_not_split_the_stretch() -> None:
    """A café stop of twenty minutes on the route is still on the route (the owner, point 1)."""
    from app.scenic_routes import advanced_m, plain_route_name

    # Ride an hour, stand twenty minutes, ride an hour -- all on one route.
    riding = list(_track(1))
    still_start = riding[-1]
    standing = [
        RoutePoint(
            timestamp=still_start.timestamp + timedelta(seconds=s),
            latitude=still_start.latitude,
            longitude=still_start.longitude,
            elevation_m=100.0,
            distance_from_start_m=still_start.distance_from_start_m,
            speed_mps=0.0,
        )
        for s in range(10, 20 * 60 + 1, 10)
    ]
    later = [
        RoutePoint(
            timestamp=p.timestamp + timedelta(hours=1, minutes=20),
            latitude=p.latitude - 3600.0 * 20.0 * _DEG_PER_M,
            longitude=p.longitude,
            elevation_m=100.0,
            distance_from_start_m=p.distance_from_start_m + 3600.0 * 20.0,
            speed_mps=20.0,
        )
        for p in _track(1)[1:]
    ]
    track = tuple(riding + standing + later)
    route = _route("R", 0.0, 2 * 3600.0)

    found = scenic_stretches(track, (route,), max_gap_s=60.0)

    assert len(found) == 1
    assert found[0].start_time == track[0].timestamp
    assert found[0].end_time == track[-1].timestamp
    assert advanced_m(track, standing[0].timestamp, standing[-1].timestamp) == 0.0
    assert plain_route_name("State Highway 1 South") == "State Highway 1"
    assert plain_route_name("Southern Scenic Route") == "Southern Scenic Route"
