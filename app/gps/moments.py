"""The moments of a day the track proves: setting off, pulling in, pulling out, arriving.

The owner's first rule for the film (2026-09-06): departure, every halt
and the arrival are always shown, and shown as the moment itself -- the
bike getting under way, slowing into a stop -- not whichever minute of
the stride scored best nearby. The stride sees twelve seconds in every
sixty and never asks when anything happened; the track knows to the
second. So these moments are read off the track and become windows of
their own (app.fixed_shots), bought like any other and then kept.

Nothing here reads the video or names a place. A halt is what
app.ride_chapters.long_halts says it is: a quarter of an hour in one
place, trimmed to where the riding stopped and started again.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.contracts import RoutePoint

# The ride is under way once it has advanced this far in this long: 300 m
# in a minute is 18 km/h, more than walking the bike across a forecourt
# and less than any road. (At 100 m the day's arrival landed seven minutes
# after the last recording, on a walk at the lodging.)
SUSTAINED_S = 60.0
SUSTAINED_M = 300.0
# Slower than this between two points is standing about, not riding.
WALKING_MPS = 1.5
# The bike is rolling once it moves this fast between two points: the
# moment to cut on is the roll-off, not a creep across the forecourt.
ROLLING_MPS = 2.5


class MomentKind(StrEnum):
    DEPARTURE = "departure"
    HALT_ARRIVAL = "halt_arrival"
    HALT_DEPARTURE = "halt_departure"
    ARRIVAL = "arrival"
    # Where the ride joins or leaves a highway (app.story_sections names them).
    HIGHWAY_ON = "highway_on"
    HIGHWAY_OFF = "highway_off"
    # Riding off a ferry (app.ferries): the first motion after the crossing.
    FERRY_OFF = "ferry_off"


@dataclass(frozen=True)
class Moment:
    """One moment of the day, on the ride's clock."""

    kind: MomentKind
    at: datetime
    # Which halt of the day, in ride order, for the two halt kinds.
    halt: int | None = None

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("a moment must be on a timezone-aware clock")
        halted = self.kind in (MomentKind.HALT_ARRIVAL, MomentKind.HALT_DEPARTURE)
        if halted != (self.halt is not None):
            raise ValueError("a halt moment names its halt; the others name none")


def _moved(points: Sequence[RoutePoint], index: int) -> bool:
    """Whether the ride advanced beyond walking pace between this point and the one before."""
    earlier, later = points[index - 1], points[index]
    elapsed = (later.timestamp - earlier.timestamp).total_seconds()
    gap = later.distance_from_start_m - earlier.distance_from_start_m
    return gap > WALKING_MPS * max(elapsed, 0.0) and gap > 0.0


def _pace(points: Sequence[RoutePoint], index: int) -> float:
    earlier, later = points[index - 1], points[index]
    elapsed = (later.timestamp - earlier.timestamp).total_seconds()
    if elapsed <= 0:
        return 0.0
    return (later.distance_from_start_m - earlier.distance_from_start_m) / elapsed


def set_off(points: Sequence[RoutePoint]) -> datetime | None:
    """When the ride first got under way, or None if it never did.

    The last still point before a move that kept going: from it the ride
    advanced `SUSTAINED_M` within `SUSTAINED_S`. A jolt across the car
    park that went nowhere is not setting off, and a creep before the
    roll-off is not it either: the moment is the last point before the
    bike first moves at `ROLLING_MPS`.
    """
    stamps = [p.timestamp for p in points]
    for index in range(1, len(points)):
        if not _moved(points, index):
            continue
        still = points[index - 1]
        reach = bisect_right(stamps, still.timestamp + timedelta(seconds=SUSTAINED_S)) - 1
        if points[reach].distance_from_start_m - still.distance_from_start_m >= SUSTAINED_M:
            rolling = index
            while rolling < reach and _pace(points, rolling) < ROLLING_MPS:
                rolling += 1
            return points[rolling - 1].timestamp
    return None


def come_to_rest(points: Sequence[RoutePoint]) -> datetime | None:
    """When the ride last stopped moving, or None if it never moved.

    The first still point after the last move that had been going on:
    up to it the ride had advanced `SUSTAINED_M` in the preceding
    `SUSTAINED_S`.
    """
    stamps = [p.timestamp for p in points]
    for index in range(len(points) - 1, 0, -1):
        if not _moved(points, index):
            continue
        stopped = points[index]
        back = bisect_left(stamps, stopped.timestamp - timedelta(seconds=SUSTAINED_S))
        if stopped.distance_from_start_m - points[back].distance_from_start_m >= SUSTAINED_M:
            rolling = index
            while rolling > back + 1 and _pace(points, rolling) < ROLLING_MPS:
                rolling -= 1
            return points[rolling].timestamp
    return None


def day_moments(
    points: Sequence[RoutePoint], halts: Sequence[tuple[datetime, datetime]]
) -> tuple[Moment, ...]:
    """Departure, both ends of every halt, and arrival, in ride order.

    A day whose track never got under way has no moments at all: there is
    no departure to show. Halts are given, so that the film and the
    judgement plan read the same ones.
    """
    began = set_off(points)
    ended = come_to_rest(points)
    if began is None or ended is None or ended <= began:
        return ()
    moments = [Moment(MomentKind.DEPARTURE, began)]
    for number, (start, end) in enumerate(sorted(halts)):
        if start <= began or end >= ended:
            continue
        moments.append(Moment(MomentKind.HALT_ARRIVAL, start, halt=number))
        moments.append(Moment(MomentKind.HALT_DEPARTURE, end, halt=number))
    moments.append(Moment(MomentKind.ARRIVAL, ended))
    return tuple(moments)
