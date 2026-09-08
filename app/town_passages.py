"""Where the ride passed through a town, from the track and the model's words.

The owner's third rule (2026-09-06): pure riding and passing through a
town are different things, and a town is a memory -- "we came through
here" -- said in a section of the leg, not a chapter of its own. A town
shows in two places at once: the track slows to street pace and keeps
stopping (lights, junctions, traffic), and the model, looking at the
windows there, calls the road a street. Only where both say so is it a
town passage; one alone is a slow road or a word.

Halts the day was cut at are not passages: standing in a car park for
half an hour is a stop, not a town. Naming the town is the place
service's job (app.place_names), done by whoever has it.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts import RoutePoint

# A point is judged by the three minutes around it.
SLOW_WINDOW_S = 180.0
# Below this mean pace over the window, with stops, the ride is in streets:
# 43 km/h, well under open-road speed and above a queue of traffic.
TOWN_MEAN_MPS = 12.0
# Slower than this is stopped.
STOP_MPS = 1.0
# Two stops in three minutes is town; one is a junction on an open road.
MIN_STOPS = 2
# Shorter than this is a village sign, not a passage.
MIN_PASSAGE_S = 120.0
# Town-like points this far apart are still one passage.
MAX_GAP_S = 120.0

# Word-bounded, not bare substrings: without \b, "city" matches inside
# "electricity" and "town" matches inside "hometown" or "uptown".
_URBAN_WORDS = re.compile(
    r"\b(?:urban|towns?|cities|city|suburbs?|streets?|residential|roundabouts?"
    r"|traffic lights?|intersections?|shops?|buildings?)\b",
    re.IGNORECASE,
)


class TownPassageError(ValueError):
    """Raised when the thresholds make no sense."""


@dataclass(frozen=True)
class TownPassage:
    """One passage through a town, on the ride's clock; named when someone can."""

    start_time: datetime
    end_time: datetime
    name: str | None = None

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise TownPassageError("a passage must cover a positive duration")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def middle(self) -> datetime:
        return self.start_time + (self.end_time - self.start_time) / 2


def says_town(text: str) -> bool:
    """Whether the model's words for a window describe a town."""
    return _URBAN_WORDS.search(text) is not None


def slow_stretches(
    points: Sequence[RoutePoint],
    *,
    halts: Sequence[tuple[datetime, datetime]] = (),
    window_s: float = SLOW_WINDOW_S,
    town_mean_mps: float = TOWN_MEAN_MPS,
    stop_mps: float = STOP_MPS,
    min_stops: int = MIN_STOPS,
    minimum_s: float = MIN_PASSAGE_S,
    max_gap_s: float = MAX_GAP_S,
) -> tuple[tuple[datetime, datetime], ...]:
    """Stretches at street pace with repeated stops, halts left out. The track's half."""
    if window_s <= 0 or town_mean_mps <= 0 or stop_mps < 0 or min_stops < 1:
        raise TownPassageError("the town thresholds must be positive")
    if minimum_s <= 0 or max_gap_s < 0:
        raise TownPassageError("the town thresholds must be positive")
    if len(points) < 2:
        return ()
    stamps = [p.timestamp for p in points]
    # Where a stop begins: a slow point after a moving one.
    stop_starts: list[datetime] = []
    was_stopped = False
    for point in points:
        stopped = (point.speed_mps or 0.0) <= stop_mps
        if stopped and not was_stopped:
            stop_starts.append(point.timestamp)
        was_stopped = stopped
    half = timedelta(seconds=window_s / 2)

    def in_halt(when: datetime) -> bool:
        return any(start <= when <= end for start, end in halts)

    def town_like(index: int) -> bool:
        when = stamps[index]
        if in_halt(when):
            return False
        first = bisect_left(stamps, when - half)
        last = bisect_right(stamps, when + half) - 1
        elapsed = (stamps[last] - stamps[first]).total_seconds()
        if elapsed <= 0:
            return False
        moved = points[last].distance_from_start_m - points[first].distance_from_start_m
        stops = bisect_right(stop_starts, stamps[last]) - bisect_left(stop_starts, stamps[first])
        return moved / elapsed < town_mean_mps and stops >= min_stops

    found: list[tuple[datetime, datetime]] = []
    run_start: datetime | None = None
    last_town: datetime | None = None
    for index in range(len(points)):
        if town_like(index):
            if run_start is None:
                run_start = stamps[index]
            last_town = stamps[index]
        elif run_start is not None and last_town is not None:
            if (stamps[index] - last_town).total_seconds() > max_gap_s:
                if (last_town - run_start).total_seconds() >= minimum_s:
                    found.append((run_start, last_town))
                run_start = last_town = None
    if run_start is not None and last_town is not None:
        if (last_town - run_start).total_seconds() >= minimum_s:
            found.append((run_start, last_town))
    return tuple(found)


def town_passages(
    points: Sequence[RoutePoint],
    hints: Mapping[datetime, str],
    *,
    halts: Sequence[tuple[datetime, datetime]] = (),
) -> tuple[TownPassage, ...]:
    """The stretches both the track and the model call a town, in ride order.

    `hints` are the model's words about judged windows, keyed by the
    window's start on the ride's clock (as app.ride_chapters takes them).
    A slow stretch with no judged window inside it, or none whose words
    say town, is not a passage: the track alone can be a slow road.
    """
    passages: list[TownPassage] = []
    for start, end in slow_stretches(points, halts=halts):
        inside = [text for when, text in hints.items() if start <= when <= end]
        if any(says_town(text) for text in inside):
            passages.append(TownPassage(start_time=start, end_time=end))
    return tuple(passages)
