"""Towns the ride came through and passes it crossed, read off reference files.

The owner's notes (2026-09-07): a city the ride passed through (day 10)
must be said in the lower third, and so must a small town when it is the
first in a long while (day 7). The earlier reading -- the track slowing
with repeated stops, and the model calling the road a street -- missed
both: a city crossed on its ring road never slows, and a village is one
straight street. So towns are now read from where they are, not from how
the ride behaved: a reference of place nodes (`places-v1`, from
OpenStreetMap, app.reference_fetch) with a radius by kind, and the ride
"came through" a place when the track passed within that radius.

Passes are the same idea with a point: a named road pass (`landmarks-v1`)
the track came within a few hundred metres of is a pass the ride crossed,
said as one line at the nearest moment.

Nothing here reads the video or sends anything anywhere.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.contracts import RoutePoint

PLACES_SCHEMA_VERSION = "places-v1"
LANDMARKS_SCHEMA_VERSION = "landmarks-v1"
DEFAULT_PLACES_DIRECTORY = Path("private-media/reference/places")
DEFAULT_LANDMARKS_DIRECTORY = Path("private-media/reference/passes")
# How far from the place's node the ride still counts as in it: a city's
# ring road is a few kilometres out; a village is its one street.
PLACE_RADIUS_M: Mapping[str, float] = {"city": 3500.0, "town": 1500.0, "village": 700.0}
# Two visits to the same place within this long are one passage (a loop
# through town, a stop on its edge).
MERGE_GAP_S = 10 * 60.0
# A pass the track came within this of was crossed.
PASS_WITHIN_M = 300.0
# Index cells of a twentieth of a degree, about five kilometres.
_CELL = 20.0
_METRES_PER_DEGREE = 111_320.0


class PlacesError(ValueError):
    """Raised when the reference cannot be read or the request is nonsense."""


@dataclass(frozen=True)
class PlaceMark:
    """One town: its name, its OSM kind, its population when known, and where it is."""

    name: str
    kind: str
    population: int | None
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PlacesError("a place needs a name")
        if self.kind not in PLACE_RADIUS_M:
            raise PlacesError("a place needs a known kind")


@dataclass(frozen=True)
class Landmark:
    """One named point on the map worth a line: a road pass."""

    name: str
    kind: str
    latitude: float
    longitude: float
    elevation_m: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.kind.strip():
            raise PlacesError("a landmark needs a name and a kind")


@dataclass(frozen=True)
class PlacePassage:
    """The ride within one place, on the ride's clock."""

    name: str
    kind: str
    population: int | None
    start_time: datetime
    end_time: datetime
    nearest_m: float

    def __post_init__(self) -> None:
        if self.end_time < self.start_time:
            raise PlacesError("a passage cannot end before it starts")

    @property
    def middle(self) -> datetime:
        return self.start_time + (self.end_time - self.start_time) / 2


@dataclass(frozen=True)
class LandmarkCrossing:
    """The moment the ride was nearest a landmark, within reach of it."""

    name: str
    kind: str
    at: datetime
    nearest_m: float
    elevation_m: float | None = None


def load_places(path: Path) -> tuple[PlaceMark, ...]:
    """The places in one reference file, refusing anything this version cannot trust."""
    payload = _read(path, PLACES_SCHEMA_VERSION)
    places: list[PlaceMark] = []
    for item in payload.get("places", ()):
        if not isinstance(item, dict):
            raise PlacesError("the places reference is malformed")
        try:
            population = item.get("population")
            places.append(
                PlaceMark(
                    name=str(item["name"]),
                    kind=str(item["kind"]),
                    population=int(population) if population is not None else None,
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PlacesError("the places reference is malformed") from error
    return tuple(places)


def load_landmarks(path: Path) -> tuple[Landmark, ...]:
    """The landmarks in one reference file."""
    payload = _read(path, LANDMARKS_SCHEMA_VERSION)
    landmarks: list[Landmark] = []
    for item in payload.get("landmarks", ()):
        if not isinstance(item, dict):
            raise PlacesError("the landmarks reference is malformed")
        try:
            elevation = item.get("elevation_m")
            landmarks.append(
                Landmark(
                    name=str(item["name"]),
                    kind=str(item["kind"]),
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                    elevation_m=float(elevation) if elevation is not None else None,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PlacesError("the landmarks reference is malformed") from error
    return tuple(landmarks)


def _read(path: Path, schema: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise PlacesError("the reference is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlacesError("the reference is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise PlacesError("unsupported reference schema")
    return payload


def _files(directory: Path) -> tuple[Path, ...]:
    if directory.is_symlink() or not directory.is_dir():
        return ()
    return tuple(sorted(p for p in directory.glob("*.json") if p.is_file() and not p.is_symlink()))


def places_or_none(directory: Path | None = None) -> tuple[PlaceMark, ...]:
    """Every place in the reference directory, or none when there is no reference."""
    found: list[PlaceMark] = []
    for path in _files(DEFAULT_PLACES_DIRECTORY if directory is None else directory):
        try:
            found.extend(load_places(path))
        except PlacesError:
            continue
    return tuple(found)


def landmarks_or_none(directory: Path | None = None) -> tuple[Landmark, ...]:
    """Every landmark in the reference directory, or none."""
    found: list[Landmark] = []
    for path in _files(DEFAULT_LANDMARKS_DIRECTORY if directory is None else directory):
        try:
            found.extend(load_landmarks(path))
        except PlacesError:
            continue
    return tuple(found)


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat * _CELL), math.floor(lon * _CELL)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = lat2 - lat1
    return math.hypot(x, y) * _METRES_PER_DEGREE


class _Grid:
    """Marks in cells, so a track point asks its neighbourhood, not the whole map."""

    def __init__(self, marks: Sequence[tuple[float, float, object]]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float, object]]] = {}
        for lat, lon, item in marks:
            self.cells.setdefault(_cell(lat, lon), []).append((lat, lon, item))

    def around(self, lat: float, lon: float) -> list[tuple[float, float, object]]:
        cx, cy = _cell(lat, lon)
        found: list[tuple[float, float, object]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                found.extend(self.cells.get((cx + dx, cy + dy), ()))
        return found


def place_passages(
    points: Sequence[RoutePoint],
    places: Sequence[PlaceMark],
    *,
    radius_m: Mapping[str, float] = PLACE_RADIUS_M,
    merge_gap_s: float = MERGE_GAP_S,
) -> tuple[PlacePassage, ...]:
    """Every place the track passed within its radius of, in ride order.

    A passage runs from the first point inside the radius to the last,
    with returns within `merge_gap_s` folded into it. Two places can
    overlap -- a suburb inside a city -- and both are reported; the caller
    decides which to say.
    """
    if merge_gap_s < 0 or any(r <= 0 for r in radius_m.values()):
        raise PlacesError("the place thresholds must be positive")
    grid = _Grid([(p.latitude, p.longitude, p) for p in places])
    reach = max(radius_m.values(), default=0.0)
    if reach > _METRES_PER_DEGREE / _CELL:
        raise PlacesError("a place radius must fit inside one index cell")
    open_runs: dict[PlaceMark, list] = {}
    found: list[PlacePassage] = []

    def close(place: PlaceMark) -> None:
        start, end, nearest = open_runs.pop(place)
        found.append(
            PlacePassage(
                name=place.name,
                kind=place.kind,
                population=place.population,
                start_time=start,
                end_time=end,
                nearest_m=nearest,
            )
        )

    for point in points:
        seen: set[PlaceMark] = set()
        for lat, lon, item in grid.around(point.latitude, point.longitude):
            place = item
            assert isinstance(place, PlaceMark)
            gap = distance_m(point.latitude, point.longitude, lat, lon)
            if gap > radius_m.get(place.kind, 0.0):
                continue
            seen.add(place)
            run = open_runs.get(place)
            if run is None:
                open_runs[place] = [point.timestamp, point.timestamp, gap]
            else:
                run[1] = point.timestamp
                run[2] = min(run[2], gap)
        for place in list(open_runs):
            if place in seen:
                continue
            if (point.timestamp - open_runs[place][1]).total_seconds() > merge_gap_s:
                close(place)
    for place in list(open_runs):
        close(place)
    return tuple(sorted(found, key=lambda p: (p.start_time, p.name)))


def landmark_crossings(
    points: Sequence[RoutePoint],
    landmarks: Sequence[Landmark],
    *,
    within_m: float = PASS_WITHIN_M,
) -> tuple[LandmarkCrossing, ...]:
    """Each landmark the track came within `within_m` of, at its nearest moment."""
    if within_m <= 0:
        raise PlacesError("the landmark reach must be positive")
    if within_m > _METRES_PER_DEGREE / _CELL:
        raise PlacesError("the landmark reach must fit inside one index cell")
    grid = _Grid([(m.latitude, m.longitude, m) for m in landmarks])
    nearest: dict[Landmark, tuple[float, datetime]] = {}
    for point in points:
        for lat, lon, item in grid.around(point.latitude, point.longitude):
            mark = item
            assert isinstance(mark, Landmark)
            gap = distance_m(point.latitude, point.longitude, lat, lon)
            if gap <= within_m and (mark not in nearest or gap < nearest[mark][0]):
                nearest[mark] = (gap, point.timestamp)
    return tuple(
        sorted(
            (
                LandmarkCrossing(
                    name=mark.name,
                    kind=mark.kind,
                    at=at,
                    nearest_m=gap,
                    elevation_m=mark.elevation_m,
                )
                for mark, (gap, at) in nearest.items()
            ),
            key=lambda c: (c.at, c.name),
        )
    )


def passage_at(passages: Sequence[PlacePassage], when: datetime) -> PlacePassage | None:
    """The largest place the ride was in at this moment, if any."""
    inside = [p for p in passages if p.start_time <= when <= p.end_time]
    if not inside:
        return None
    order = {"city": 0, "town": 1, "village": 2}
    return min(inside, key=lambda p: (order.get(p.kind, 9), -(p.population or 0)))


def within(points: Sequence[RoutePoint], when: datetime, slack: timedelta) -> bool:
    """Whether the track has a point within `slack` of this moment."""
    stamps = [p.timestamp for p in points]
    index = bisect_right(stamps, when)
    for candidate in (index - 1, index):
        if 0 <= candidate < len(stamps) and abs(stamps[candidate] - when) <= slack:
            return True
    return False
