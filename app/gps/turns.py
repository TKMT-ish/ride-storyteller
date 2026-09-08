"""Sharp turns read off the track: the moments a ride visibly changes direction.

docs/completion-roadmap-ja.md Q1: the owner missed a big turn that the
film never showed. Candidate windows are cut from the footage every thirty
seconds (app.footage_candidates), so more than half of every recording is
never judged, and a corner that falls between two windows is never seen.
The track knows where the corners are. This module finds them, and nothing
else: it names no place and reads no map. A turn is a span of the ride, on
the ride's own clock, with how far the heading swung.

The per-sample direction events in app.gps.events fire on any two points
that disagree by sixty degrees, which at a standstill is GPS noise: the
second day of the real ride had 426 of them. A sharp turn here is heading
that keeps swinging the same way over several seconds at riding speed --
the thing a rider feels and a camera sees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.contracts import RoutePoint

# What the second day of the real ride, read locally, made of the thresholds:
# 90 degrees within 10 s at riding speed found 83 turns, 47 of them between
# judged windows; 110 degrees found 40 and 25. Ninety is a proper corner.
DEFAULT_MIN_DEGREES = 90.0
DEFAULT_SPAN_S = 10.0
# Below walking-into-a-car-park speed a heading is noise, not a turn.
DEFAULT_MIN_SPEED_MPS = 4.0


class SharpTurnError(ValueError):
    """Raised when the thresholds cannot describe a turn."""


@dataclass(frozen=True)
class SharpTurn:
    """One turn: when it began and ended, and how far the heading swung.

    `degrees` is signed: positive clockwise (a right turn), negative
    counter-clockwise. Its size is the whole swing over the span.
    """

    start_time: datetime
    end_time: datetime
    degrees: float

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("a turn must take some time")
        if self.degrees == 0:
            raise ValueError("a turn swings the heading")

    @property
    def middle(self) -> datetime:
        return self.start_time + (self.end_time - self.start_time) / 2

    @property
    def is_right(self) -> bool:
        return self.degrees > 0

    def to_dict(self) -> dict[str, object]:
        """Aggregates only: no coordinate, no timestamp."""
        return {
            "duration_s": round((self.end_time - self.start_time).total_seconds(), 3),
            "degrees": round(self.degrees, 1),
        }


def sharp_turns(
    points: tuple[RoutePoint, ...],
    *,
    min_degrees: float = DEFAULT_MIN_DEGREES,
    span_s: float = DEFAULT_SPAN_S,
    min_speed_mps: float = DEFAULT_MIN_SPEED_MPS,
) -> tuple[SharpTurn, ...]:
    """Every stretch where the heading swings at least `min_degrees` within `span_s`.

    The heading is summed point to point from each candidate start, while
    the rider keeps moving; when the sum reaches the threshold the turn is
    recorded and the search resumes after it, so one corner is one turn.
    A stop inside the span ends the attempt: a turn made while parking is
    not a turn.
    """
    if min_degrees <= 0 or span_s <= 0 or min_speed_mps < 0:
        raise SharpTurnError("turn thresholds must be positive")
    turns: list[SharpTurn] = []
    count = len(points)
    index = 0
    while index < count - 2:
        if (points[index].speed_mps or 0.0) < min_speed_mps:
            index += 1
            continue
        swing = 0.0
        previous_bearing = _bearing(points[index], points[index + 1])
        stopped = False
        cursor = index + 1
        while cursor < count - 1 and _seconds_between(points[index], points[cursor]) <= span_s:
            if (points[cursor].speed_mps or 0.0) < min_speed_mps:
                stopped = True
                break
            bearing = _bearing(points[cursor], points[cursor + 1])
            swing += _turned(previous_bearing, bearing)
            previous_bearing = bearing
            cursor += 1
            if abs(swing) >= min_degrees:
                break
        if not stopped and abs(swing) >= min_degrees:
            turns.append(
                SharpTurn(
                    start_time=points[index].timestamp,
                    end_time=points[cursor].timestamp,
                    degrees=swing,
                )
            )
            index = cursor
            continue
        index += 1
    return tuple(turns)


def _seconds_between(first: RoutePoint, second: RoutePoint) -> float:
    return (second.timestamp - first.timestamp).total_seconds()


def _bearing(start: RoutePoint, end: RoutePoint) -> float:
    lat1, lat2 = math.radians(start.latitude), math.radians(end.latitude)
    dlon = math.radians(end.longitude - start.longitude)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _turned(first: float, second: float) -> float:
    """The signed change of heading, in [-180, 180): positive is clockwise.

    A dead U-turn (a 180 degree swing either way) lands on -180.0, never
    +180.0 -- the modulo picks a side rather than leaving the sign
    undecided, so the boundary itself is a fixed, if arbitrary, choice.
    """
    return (second - first + 180.0) % 360.0 - 180.0
