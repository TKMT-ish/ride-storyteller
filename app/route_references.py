"""What the reference files say about the day: scenic stretches, highway runs, road moments.

Shared by the judgement plan and the film so that both read the same
moments off the same references -- a window the plan buys for joining a
highway is the window the film keeps for it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from app.agents.story_planner import StoryOutputLanguage
from app.contracts import RoutePoint
from app.ferries import FerryCrossing
from app.gps.moments import Moment, MomentKind, set_off
from app.place_names import PlaceNames, PlaceNamesError
from app.reference_fetch import ReferenceFetchError, read_names
from app.scenic_routes import (
    ScenicRoutesError,
    ScenicStretch,
    advanced_m,
    load_touring_routes,
    plain_route_name,
    reference_files,
    scenic_stretches,
)
from app.story_sections import OFF_HIGHWAY_FOR_S, highway_entries, highway_exits

# The highways reference (app.scenic_routes shape), beside the scenic one.
HIGHWAYS_DIRECTORY = Path("private-media/reference/highways")
# Roads with a name worth saying (the owner, 2026-09-07: the famous road on
# day 2): the OpenStreetMap lines fetched for the names in `wanted.txt`,
# and the names themselves, which the place service's road names are
# matched against for roads the map does not carry by that name.
NAMED_ROADS_DIRECTORY = Path("private-media/reference/named-roads")
WANTED_ROADS_FILE_NAME = "wanted.txt"
ROAD_MIN_S = 5 * 60.0
ROAD_MAX_GAP_S = 10 * 60.0
# The place service is asked for the road every so often along the track.
ROAD_SAMPLE_S = 180.0
# A named road that is itself a signposted route is a chapter, not only a line.
_ROUTE_NAMES = re.compile(
    r"scenic route|touring route|heritage trail|wine trail|explorer highway|world highway",
    re.IGNORECASE,
)
# Riding off the ferry within this long of the crossing's end is the crossing's end.
FERRY_OFF_WITHIN_S = 30 * 60.0


def scenic_or_none(points: tuple[RoutePoint, ...]) -> tuple[ScenicStretch, ...]:
    """The day's runs along official scenic routes, or none when there is no reference."""
    stretches: list[ScenicStretch] = []
    for path in reference_files():
        try:
            stretches.extend(scenic_stretches(points, load_touring_routes(path)))
        except ScenicRoutesError:
            continue
    return tuple(sorted(stretches, key=lambda s: s.start_time))


def highway_runs(points: tuple[RoutePoint, ...]) -> tuple[ScenicStretch, ...]:
    """The day's runs along the highways reference, or none without one."""
    runs: list[ScenicStretch] = []
    for path in reference_files(HIGHWAYS_DIRECTORY):
        try:
            highways = tuple(
                replace(route, name=plain_route_name(route.name))
                for route in load_touring_routes(path)
            )
            runs.extend(
                scenic_stretches(
                    points, highways, minimum_s=OFF_HIGHWAY_FOR_S, max_gap_s=OFF_HIGHWAY_FOR_S
                )
            )
        except ScenicRoutesError:
            continue
    return tuple(sorted(runs, key=lambda s: s.start_time))


def road_moments(
    points: tuple[RoutePoint, ...], runs: tuple[ScenicStretch, ...]
) -> tuple[Moment, ...]:
    """Joining and leaving a highway, as moments that get a shot of their own."""
    if not points:
        return ()
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    language = StoryOutputLanguage.JAPANESE  # the line is not used here, only the moment
    advanced = lambda since, until: advanced_m(points, since, until)  # noqa: E731
    joined = highway_entries(runs, ride_start=ride_start, language=language, advanced=advanced)
    left = highway_exits(runs, ride_end=ride_end, language=language, advanced=advanced)
    return tuple(
        sorted(
            (
                *(Moment(MomentKind.HIGHWAY_ON, e.at) for e in joined),
                *(Moment(MomentKind.HIGHWAY_OFF, e.at) for e in left),
            ),
            key=lambda m: m.at,
        )
    )


def real_scenic(
    stretches: tuple[ScenicStretch, ...], runs: tuple[ScenicStretch, ...], *, edge_s: float = 120.0
) -> tuple[ScenicStretch, ...]:
    """The scenic stretches whose ends are the ride's, not the reference's.

    A touring route's relation can begin somewhere along a state highway;
    a ride already on that highway did not "enter" anything there. A
    stretch end that lies inside one highway run, more than `edge_s` from
    that run's own ends, is such an edge, and the stretch is dropped.
    """
    edge = timedelta(seconds=edge_s)

    def inside_a_run(when: datetime) -> bool:
        return any(run.start_time + edge < when < run.end_time - edge for run in runs)

    return tuple(
        s for s in stretches if not inside_a_run(s.start_time) and not inside_a_run(s.end_time)
    )


def wanted_road_names(directory: Path | None = None) -> tuple[str, ...]:
    """The road names worth a line, from the private list; none without one."""
    where = NAMED_ROADS_DIRECTORY if directory is None else directory
    try:
        return read_names(where / WANTED_ROADS_FILE_NAME)
    except ReferenceFetchError:
        return ()


def is_route_name(name: str) -> bool:
    """Whether a named road is a signposted route -- a chapter of its own, like a scenic route."""
    return _ROUTE_NAMES.search(name) is not None


def _plain(name: str) -> str:
    """A name without accents or case, so two spellings of one road are one road."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)
    )
    return " ".join(stripped.casefold().split())


def mapped_road_runs(
    points: tuple[RoutePoint, ...], directory: Path | None = None
) -> tuple[ScenicStretch, ...]:
    """The day's runs along the named roads the map carries, or none without a reference."""
    runs: list[ScenicStretch] = []
    for path in reference_files(NAMED_ROADS_DIRECTORY if directory is None else directory):
        try:
            runs.extend(
                scenic_stretches(
                    points,
                    load_touring_routes(path),
                    minimum_s=ROAD_MIN_S,
                    max_gap_s=ROAD_MAX_GAP_S,
                )
            )
        except ScenicRoutesError:
            continue
    return tuple(sorted(runs, key=lambda s: s.start_time))


def sampled_road_runs(
    points: Sequence[RoutePoint],
    names: PlaceNames,
    wanted: Sequence[str],
    *,
    step_s: float = ROAD_SAMPLE_S,
    minimum_s: float = ROAD_MIN_S,
) -> tuple[ScenicStretch, ...]:
    """The day's runs along wanted roads, read from the place service's road names.

    One coordinate every `step_s` along the track is named; consecutive
    samples on the same wanted road are one run, from the first sample to
    the last plus a step. A road the service cannot name breaks nothing:
    the sample is simply not on any wanted road.
    """
    if step_s <= 0 or minimum_s <= 0:
        raise ValueError("the sampling step and the minimum must be positive")
    lookup = {_plain(name): name for name in wanted if name.strip()}
    if not lookup or not points:
        return ()
    step = timedelta(seconds=step_s)
    runs: list[ScenicStretch] = []
    current: tuple[str, datetime, datetime] | None = None
    next_sample = points[0].timestamp
    for point in points:
        if point.timestamp < next_sample:
            continue
        next_sample = point.timestamp + step
        try:
            road = names.name_at(point.latitude, point.longitude).road
        except PlaceNamesError:
            road = None
        wanted_name = lookup.get(_plain(road)) if road else None
        if wanted_name is not None and current is not None and current[0] == wanted_name:
            current = (wanted_name, current[1], point.timestamp)
            continue
        if current is not None:
            _close_run(runs, current, step, minimum_s)
        current = (wanted_name, point.timestamp, point.timestamp) if wanted_name else None
    if current is not None:
        _close_run(runs, current, step, minimum_s)
    return tuple(runs)


def _close_run(
    runs: list[ScenicStretch],
    current: tuple[str, datetime, datetime],
    step: timedelta,
    minimum_s: float,
) -> None:
    name, first, last = current
    end = last + step
    if (end - first).total_seconds() >= minimum_s:
        runs.append(ScenicStretch(route=name, start_time=first, end_time=end))


def road_runs(
    points: tuple[RoutePoint, ...], names: PlaceNames | None, *, directory: Path | None = None
) -> tuple[ScenicStretch, ...]:
    """Every run along a named road the day has, from the map and from the place service.

    Where both know the road, the longer run keeps its span; nothing overlaps.
    """
    found = list(mapped_road_runs(points, directory))
    if names is not None:
        found.extend(sampled_road_runs(points, names, wanted_road_names(directory)))
    kept: list[ScenicStretch] = []
    for run in sorted(found, key=lambda r: (-r.duration_s, r.start_time)):
        if all(run.end_time <= o.start_time or run.start_time >= o.end_time for o in kept):
            kept.append(run)
    return tuple(sorted(kept, key=lambda r: r.start_time))


def ferry_moments(
    points: tuple[RoutePoint, ...], crossings: Sequence[FerryCrossing]
) -> tuple[Moment, ...]:
    """Riding off each ferry: the ride's first motion after the crossing, as its own shot."""
    moments: list[Moment] = []
    for crossing in crossings:
        after = [p for p in points if p.timestamp >= crossing.end_time]
        moved = set_off(after) if len(after) >= 2 else None
        at = crossing.end_time
        if moved is not None and (moved - crossing.end_time).total_seconds() <= FERRY_OFF_WITHIN_S:
            at = moved
        moments.append(Moment(MomentKind.FERRY_OFF, at))
    return tuple(moments)


def clear_of_crossings(
    moments: Sequence[Moment], crossings: Sequence[FerryCrossing], *, slack_s: float = 20 * 60.0
) -> tuple[Moment, ...]:
    """The moments that are not the ship's: none within `slack_s` of a crossing's ends."""
    slack = timedelta(seconds=slack_s)
    return tuple(
        m
        for m in moments
        if not any(c.start_time - slack <= m.at <= c.end_time + slack for c in crossings)
    )
