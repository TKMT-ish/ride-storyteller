"""Which stretches of a day ran along an official scenic route, from a reference file.

The owner's fifth rule (2026-09-06): when the ride followed a designated
scenic route, that part of the day is one chapter, named for the route.
"Designated" is a fact about the road, not about the view, so it is read
from a reference file of official routes -- for New Zealand, the touring
routes OpenStreetMap carries as route relations -- kept under
`private-media/reference/touring-routes/` and never in git. Matching is
done here on the machine: a track point is on a route when it lies within
`ON_ROUTE_M` of any point of the route's lines, and a stretch is a run of
such points long enough to be a chapter, with gaps shorter than a short
detour allowed.

The file's shape (`touring-routes-v1`): `routes`, each with a `name` and
`lines` -- lists of [latitude, longitude] pairs. Nothing here sends
anything anywhere, and nothing reads the video.
"""

from __future__ import annotations

import json
import math
import os
import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.contracts import RoutePoint

TOURING_ROUTES_SCHEMA_VERSION = "touring-routes-v1"
DEFAULT_REFERENCE_DIRECTORY = Path("private-media/reference/touring-routes")
TOURING_ROUTES_ENV = "RIDE_TOURING_ROUTES"
# A track point this close to the route's line is on it: GPS wander plus
# the width of a highway and its verge.
ON_ROUTE_M = 150.0
# A stretch shorter than this is not a chapter of the day.
MIN_STRETCH_S = 15 * 60.0
# The ride may leave the route for this long (a fuel stop, a detour to a
# lookout, a town's bypass) and still be on it -- the owner's note
# (2026-09-06, point 1): a stretch left for a while is not an exit.
MAX_GAP_S = 10 * 60.0
# Two runs along one route with less riding than this between them are one
# run: the ride stood at a lookout or a café, it did not leave the route.
MERGE_UNDER_M = 5_000.0
# Grid cells of a hundredth of a degree, about a kilometre, for the index.
_CELL = 100.0
_METRES_PER_DEGREE = 111_320.0


class ScenicRoutesError(ValueError):
    """Raised when the reference cannot be read or the request is nonsense."""


@dataclass(frozen=True)
class TouringRoute:
    """One official route: its name and its lines."""

    name: str
    lines: tuple[tuple[tuple[float, float], ...], ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ScenicRoutesError("a route needs a name")
        if not any(self.lines):
            raise ScenicRoutesError("a route needs at least one line with points")


@dataclass(frozen=True)
class ScenicStretch:
    """A run of the day's track along one route."""

    route: str
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ScenicRoutesError("a stretch must cover a positive duration")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


def load_touring_routes(path: Path) -> tuple[TouringRoute, ...]:
    """The routes in one reference file, refusing anything this version cannot trust."""
    if path.is_symlink() or not path.is_file():
        raise ScenicRoutesError("the touring-routes reference is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenicRoutesError("the touring-routes reference is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema") != TOURING_ROUTES_SCHEMA_VERSION:
        raise ScenicRoutesError("unsupported touring-routes schema")
    routes: list[TouringRoute] = []
    for item in payload.get("routes", ()):
        if not isinstance(item, dict):
            raise ScenicRoutesError("the touring-routes reference is malformed")
        name = item.get("name")
        lines = item.get("lines")
        if not isinstance(name, str) or not isinstance(lines, list):
            raise ScenicRoutesError("the touring-routes reference is malformed")
        try:
            routes.append(
                TouringRoute(
                    name=name,
                    lines=tuple(
                        tuple((float(lat), float(lon)) for lat, lon in line) for line in lines
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise ScenicRoutesError("the touring-routes reference is malformed") from error
    return tuple(routes)


def reference_files(directory: Path | None = None) -> tuple[Path, ...]:
    """Every reference file to match against: the environment's, else the directory's."""
    named = os.environ.get(TOURING_ROUTES_ENV, "").strip()
    if named:
        return (Path(named),)
    where = DEFAULT_REFERENCE_DIRECTORY if directory is None else directory
    if where.is_symlink() or not where.is_dir():
        return ()
    return tuple(sorted(p for p in where.glob("*.json") if p.is_file() and not p.is_symlink()))


class _RouteIndex:
    """The route's points in a grid, so a track point asks a few cells, not all."""

    def __init__(self, route: TouringRoute) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for line in route.lines:
            for lat, lon in line:
                self.cells.setdefault(_cell(lat, lon), []).append((lat, lon))

    def near(self, lat: float, lon: float, radius_m: float) -> bool:
        cx, cy = _cell(lat, lon)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for qlat, qlon in self.cells.get((cx + dx, cy + dy), ()):
                    if _distance_m(lat, lon, qlat, qlon) <= radius_m:
                        return True
        return False


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat * _CELL), math.floor(lon * _CELL)


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = lat2 - lat1
    return math.hypot(x, y) * _METRES_PER_DEGREE


def scenic_stretches(
    points: Sequence[RoutePoint],
    routes: Sequence[TouringRoute],
    *,
    on_route_m: float = ON_ROUTE_M,
    minimum_s: float = MIN_STRETCH_S,
    max_gap_s: float = MAX_GAP_S,
) -> tuple[ScenicStretch, ...]:
    """The day's runs along each route, in ride order, each long enough to be a chapter.

    Where two routes share a road, the one the ride followed longer that
    day wins the shared stretch; stretches never overlap.
    """
    if on_route_m <= 0 or minimum_s <= 0 or max_gap_s < 0:
        raise ScenicRoutesError("the matching thresholds must be positive")
    found: list[ScenicStretch] = []
    for route in routes:
        index = _RouteIndex(route)
        runs: list[tuple[datetime, datetime]] = []
        run_start: datetime | None = None
        last_on: datetime | None = None
        for point in points:
            if index.near(point.latitude, point.longitude, on_route_m):
                if run_start is None:
                    run_start = point.timestamp
                last_on = point.timestamp
            elif run_start is not None and last_on is not None:
                if (point.timestamp - last_on).total_seconds() > max_gap_s:
                    runs.append((run_start, last_on))
                    run_start = last_on = None
        if run_start is not None and last_on is not None:
            runs.append((run_start, last_on))
        for start, end in _joined_across_halts(runs, points):
            _close(found, route.name, start, end, minimum_s)
    return _without_overlaps(found)


def _joined_across_halts(
    runs: list[tuple[datetime, datetime]], points: Sequence[RoutePoint]
) -> list[tuple[datetime, datetime]]:
    """Runs with less than `MERGE_UNDER_M` of riding between them become one."""
    joined: list[tuple[datetime, datetime]] = []
    for start, end in runs:
        if joined and advanced_m(points, joined[-1][1], start) < MERGE_UNDER_M:
            joined[-1] = (joined[-1][0], end)
        else:
            joined.append((start, end))
    return joined


def advanced_m(points: Sequence[RoutePoint], since: datetime, until: datetime) -> float:
    """How far the track advanced between two moments."""
    stamps = [p.timestamp for p in points]
    first = min(len(points) - 1, bisect_right(stamps, since) - 1)
    last = min(len(points) - 1, bisect_right(stamps, until) - 1)
    if first < 0 or last < 0:
        return 0.0
    return max(0.0, points[last].distance_from_start_m - points[first].distance_from_start_m)


_DIRECTION = re.compile(r"\s+(?:north|south|east|west)(?:bound)?$", re.IGNORECASE)


def plain_route_name(name: str) -> str:
    """A highway's name without the carriageway's direction: "State Highway 1 South" is SH 1."""
    return _DIRECTION.sub("", name.strip())


def _close(
    found: list[ScenicStretch], name: str, start: datetime, end: datetime, minimum_s: float
) -> None:
    if (end - start).total_seconds() >= minimum_s:
        found.append(ScenicStretch(route=name, start_time=start, end_time=end))


def _without_overlaps(found: list[ScenicStretch]) -> tuple[ScenicStretch, ...]:
    """Longer stretches keep their span; a shorter one overlapping them is dropped."""
    kept: list[ScenicStretch] = []
    for stretch in sorted(found, key=lambda s: (-s.duration_s, s.start_time)):
        if all(
            stretch.end_time <= other.start_time or stretch.start_time >= other.end_time
            for other in kept
        ):
            kept.append(stretch)
    return tuple(sorted(kept, key=lambda s: s.start_time))


def stretch_at(stretches: Sequence[ScenicStretch], when: datetime) -> ScenicStretch | None:
    """The stretch covering this moment, if any."""
    starts = [s.start_time for s in stretches]
    index = bisect_right(starts, when) - 1
    if index >= 0 and stretches[index].start_time <= when < stretches[index].end_time:
        return stretches[index]
    return None


def stretches_within(
    stretches: Sequence[ScenicStretch], start: datetime, end: datetime
) -> tuple[ScenicStretch, ...]:
    """The stretches that fall inside this span, clipped to it."""
    inside: list[ScenicStretch] = []
    for stretch in stretches:
        a, b = max(stretch.start_time, start), min(stretch.end_time, end)
        if b > a:
            inside.append(ScenicStretch(route=stretch.route, start_time=a, end_time=b))
    return tuple(inside)


def timedelta_s(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)
