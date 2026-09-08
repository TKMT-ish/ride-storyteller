"""Where the ride was carried by a ferry, from the track and a reference of routes.

The owner's day-3 note (2026-09-07): boarding the ferry is the event of
the day and the film said nothing; worse, the track's hours at sea read
as riding -- a highway exit fired as the ship left the wharf, and the
chapter called the crossing "along the coast". A crossing is read off a
reference of ferry lines (`touring-routes-v1`, from OpenStreetMap,
app.reference_fetch): a run of the track within `ON_FERRY_M` of a line,
long enough to be a crossing, at a ship's pace throughout. Everything
that reads the track then knows those minutes were not ridden.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.contracts import RoutePoint
from app.scenic_routes import (
    ScenicRoutesError,
    ScenicStretch,
    TouringRoute,
    advanced_m,
    load_touring_routes,
    reference_files,
    scenic_stretches,
)

DEFAULT_FERRIES_DIRECTORY = Path("private-media/reference/ferries")
# A ship keeps within this of its charted line -- the charted lines are
# coarse, and a ship in a strait wanders further than a road does.
ON_FERRY_M = 3000.0
# Shorter than this is a harbour hop, not a crossing worth a chapter.
MIN_CROSSING_S = 15 * 60.0
# Mid-strait the track leaves the charted line for a long while and comes
# back to it -- or the receiver gives up entirely -- and that is one
# crossing, not two.
MAX_GAP_S = 2 * 60 * 60.0
# No ship the ride will take keeps this up; a road along the water does.
# Read as a median over the crossing, because a receiver on a vehicle deck
# throws out single readings of a hundred metres a second.
SHIP_MAX_MPS = 14.0
PACE_WINDOW_S = 60.0
# A crossing carries the ride this far at least: a harbour road within
# reach of the charted line never does.
MIN_CROSSING_M = 10_000.0


class FerriesError(ValueError):
    """Raised when the reference cannot be read or the request is nonsense."""


@dataclass(frozen=True)
class FerryCrossing:
    """One crossing: the ferry's name and when the track was aboard."""

    name: str
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise FerriesError("a crossing must cover a positive duration")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


def ferries_or_none(directory: Path | None = None) -> tuple[TouringRoute, ...]:
    """Every ferry line in the reference directory, or none when there is no reference."""
    routes: list[TouringRoute] = []
    for path in reference_files(DEFAULT_FERRIES_DIRECTORY if directory is None else directory):
        try:
            routes.extend(load_touring_routes(path))
        except ScenicRoutesError:
            continue
    return tuple(routes)


def ferry_crossings(
    points: Sequence[RoutePoint],
    routes: Sequence[TouringRoute],
    *,
    on_ferry_m: float = ON_FERRY_M,
    minimum_s: float = MIN_CROSSING_S,
    max_gap_s: float = MAX_GAP_S,
    ship_max_mps: float = SHIP_MAX_MPS,
    minimum_m: float = MIN_CROSSING_M,
    witnessed: Sequence[datetime] = (),
    aboard: Sequence[datetime] = (),
    halts: Sequence[tuple[datetime, datetime]] = (),
) -> tuple[FerryCrossing, ...]:
    """The day's crossings, in ride order.

    A crossing is the whole run along a charted ferry line -- the queue at
    the terminal, the sailing, the wait to ride off -- because the track
    cannot tell the queue from the deck: on the deck the bike is parked
    and the receiver loses the sky, so both read as standing still. What
    keeps a harbour road out is the run's own shape: it must last, it must
    carry the ride ten kilometres, and half of its minutes must be slower
    than any ship's limit.

    And the camera must have seen the ride carried. `aboard` are the
    moments of windows showing a deck, a bow, the vessel's inside; a run
    with none of them is a road that happens to follow the charted line
    (a sound's shore road did for an hour and a half, and a town's main
    street with a sign to the terminal did for another). `witnessed` is
    the wider set -- the terminal and the ramp as well -- and fixes where
    the crossing begins: the halt in `halts` holding the first of them,
    because the wait at the terminal is part of taking the ferry and the
    road that got there is not.
    """
    if ship_max_mps <= 0:
        raise FerriesError("a ship's pace must be positive")
    try:
        runs = scenic_stretches(
            points, routes, on_route_m=on_ferry_m, minimum_s=minimum_s, max_gap_s=max_gap_s
        )
    except ScenicRoutesError as error:
        raise FerriesError(str(error)) from error
    crossings: list[FerryCrossing] = []
    for run in runs:
        if advanced_m(points, run.start_time, run.end_time) < minimum_m:
            continue
        if not _paced_like_a_ship(points, run, ship_max_mps):
            continue
        if not any(run.start_time <= w <= run.end_time for w in aboard):
            continue
        seen = [w for w in sorted(witnessed) if run.start_time <= w <= run.end_time]
        if not seen:
            continue
        start = _queued_from(seen[0], halts, run.start_time)
        if run.end_time <= start:
            continue
        crossings.append(FerryCrossing(name=run.route, start_time=start, end_time=run.end_time))
    return tuple(_without_overlap(crossings))


def _queued_from(
    first_witness: datetime, halts: Sequence[tuple[datetime, datetime]], fallback: datetime
) -> datetime:
    """Where the wait for this ferry began: the halt holding the first sight of it."""
    for start, end in sorted(halts):
        if start <= first_witness <= end:
            return max(start, fallback)
    return fallback


def _without_overlap(crossings: Sequence[FerryCrossing]) -> list[FerryCrossing]:
    """One crossing where two charted lines matched the same water."""
    kept: list[FerryCrossing] = []
    for crossing in sorted(crossings, key=lambda c: (-c.duration_s, c.start_time)):
        if all(
            crossing.end_time <= k.start_time or crossing.start_time >= k.end_time for k in kept
        ):
            kept.append(crossing)
    return sorted(kept, key=lambda c: c.start_time)


def _paced_like_a_ship(points: Sequence[RoutePoint], run: ScenicStretch, limit: float) -> bool:
    """Whether the track kept a ship's pace across this span, taken as a median.

    A receiver on a vehicle deck loses the sky and comes back with a jump,
    so single readings say nothing; half the minutes of a crossing are
    slower than a ship, and half the minutes of a road ride are not.
    """
    paces = _window_paces(points, run)
    if not paces:
        return False
    paces.sort()
    middle = paces[len(paces) // 2]
    return middle <= limit


def _window_paces(points: Sequence[RoutePoint], run: ScenicStretch) -> list[float]:
    """The pace over each minute of the span, in metres a second."""
    stamps = [p.timestamp for p in points]
    first = bisect_right(stamps, run.start_time) - 1
    last = bisect_right(stamps, run.end_time) - 1
    if first < 0 or last <= first:
        return []
    window = timedelta(seconds=PACE_WINDOW_S)
    paces: list[float] = []
    index = first
    while index < last:
        until = points[index].timestamp + window
        ahead = min(last, bisect_right(stamps, until) - 1)
        if ahead <= index:
            index += 1
            continue
        elapsed = (points[ahead].timestamp - points[index].timestamp).total_seconds()
        moved = points[ahead].distance_from_start_m - points[index].distance_from_start_m
        if elapsed > 0:
            paces.append(moved / elapsed)
        index = ahead
    return paces


def crossing_distance_m(points: Sequence[RoutePoint], crossings: Sequence[FerryCrossing]) -> float:
    """How far the track advanced while afloat -- not ridden, and not to be counted so."""
    return sum(advanced_m(points, c.start_time, c.end_time) for c in crossings)


def afloat(crossings: Sequence[FerryCrossing], when: datetime, slack_s: float = 0.0) -> bool:
    """Whether the ride was on a ferry at this moment, give or take `slack_s`."""
    slack = timedelta(seconds=slack_s)
    return any(c.start_time - slack <= when <= c.end_time + slack for c in crossings)


def crossing_at(crossings: Sequence[FerryCrossing], when: datetime) -> FerryCrossing | None:
    for crossing in crossings:
        if crossing.start_time <= when <= crossing.end_time:
            return crossing
    return None
