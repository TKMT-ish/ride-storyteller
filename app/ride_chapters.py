"""Cut one day's ride into a few chapters, and say what each one was.

The film used to carry a card for every unfilmed stretch between two
adopted windows: twenty-one cards on the real second day, eleven of them
saying the road continued, each with a body of numbers. The owner called
it no story, and the research (docs/research-touring-video-quality-ja.md)
agrees on why: a well-regarded touring film is a handful of chapters with
a shape -- departure, the road, the destination, the afterglow, the end --
and a chapter is where the character of the ride changes, not wherever
the camera happened to be off.

So the track is cut first, into four to six chapters, at the places the
GPS proves something changed: a halt long enough to be an event, a pass
with real climbing on both sides, and beyond those the longest stretches
split in two so that no chapter runs a third of the day. Each chapter is
then named from its own evidence -- net climb or descent, a pass at its
end, low flat ground, a road that keeps turning, a fast straight run --
and from the words the model used for the windows inside it, so that a
stretch the model called coastal can be called coastal here. No title is
used twice in one film, and the body states what the track proves: how
long since departure, how far, how high.

Nothing here reads a place name, because there is none to read, and
nothing asks the rider anything. The chapters exist so that the windows
the judgement chose can be shown in a day that has a shape.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.agents.story_planner import StoryOutputLanguage
from app.contracts import RoutePoint
from app.ferries import FerryCrossing
from app.gap_chapters import GapChapterCard, GapCharacter
from app.gps.elevation import gain_and_loss
from app.journey_gaps import JourneyGapKind, JourneyGapSegment
from app.place_names import PlaceName
from app.scenic_routes import ScenicStretch
from app.story_timeline import StoryBeat, StoryBeatKind, StoryTimeline, TimelineFootage

RIDE_CHAPTER_SCHEMA_VERSION = "ride-chapters-v1"

# A day reads as a story at this many chapters: fewer is a slideshow with
# one card, more is the old pile of link cards.
MIN_CHAPTERS = 1
MAX_CHAPTERS = 6
# The owner's frame (2026-09-06, point 7; 2026-09-07 on day 1): departure,
# the rest points, the stopovers and the arrival are the cuts -- a stop of
# five minutes counts -- and only a day with none of them is cut into
# about five parts instead.
TARGET_CHAPTERS = 5
# A stop of five minutes is a stopover: a section, with its own shots. A
# stop of fifteen cuts a leg. A day with fewer than MIN_LEGS legs from its
# long halts promotes its longest short stops to cuts (the owner, 2026-09-07:
# day 1's fuel stops become small cuts because the day has no other).
STOP_MIN_S = 5 * 60.0
MIN_LEGS = 3
# A leg longer than this is cut -- at a pass it crosses, else into even
# parts -- so a day with no stop still has a shape.
LONG_LEG_S = 2 * 3600.0
# A halt this long is an event in the day, not a traffic light.
LONG_HALT_S = 15 * 60.0
# Within this much track distance the ride is still at the same place, and
# at walking pace it is still there however long it wanders: a rider
# pushing round a car park or walking through a museum with the camera on.
HALT_RADIUS_M = 300.0
WALKING_MPS = 1.5
# A pass needs this much climbing before it and descent after it to be
# called one, rather than a bump on a plateau.
PASS_PROMINENCE_M = 300.0
# Chapters shorter than this say nothing a viewer can follow.
MIN_CHAPTER_S = 20 * 60.0
# Net elevation past this is a climb or a descent, as for gap cards.
NET_ELEVATION_M = 150.0
# Ground this low, for this far, is the flat land by the water or a plain.
LOWLAND_M = 30.0
LOWLAND_MIN_DISTANCE_M = 10_000.0
# A road that turns this much per kilometre is a road that keeps turning.
WINDING_DEG_PER_KM = 40.0
# Faster than this on average is an open road eating distance.
FAST_MPS = 22.0
# Screen time a chapter card is held: long enough to read a title and one
# line, short enough not to stall the film (lower-third guidance: 4-7 s).
CHAPTER_CARD_S = 6.0
# Elevation change worth stating on a card.
ELEVATION_WORTH_STATING_M = 100.0

_COAST_WORDS = ("coast", "sea", "ocean", "lake", "shore", "beach", "harbour", "harbor", "bay")
_TOWN_WORDS = ("town", "city", "urban", "suburban", "street", "village")


class RideChapterError(ValueError):
    """Raised when a ride cannot be cut into chapters as asked."""


@dataclass(frozen=True)
class RideChapter:
    """One stretch of the day with one character, on the ride's clock."""

    start_time: datetime
    end_time: datetime
    character: GapCharacter
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    start_elevation_m: float | None
    end_elevation_m: float | None
    since_departure_s: float
    # How long the ride stood at the end of this leg: the halt that cut it.
    halt_s: float = 0.0
    # The official scenic route this leg ran along, when it was cut for one.
    route_name: str | None = None

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("a chapter must cover a positive duration")
        if self.distance_m < 0 or self.elevation_gain_m < 0 or self.elevation_loss_m < 0:
            raise ValueError("a chapter's aggregates cannot be negative")
        if self.halt_s < 0:
            raise RideChapterError("a leg cannot stand for a negative time")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, object]:
        """Aggregates only: no coordinate, timestamp, or identifier."""
        return {
            "character": self.character.value,
            "duration_s": round(self.duration_s, 3),
            "distance_m": round(self.distance_m, 3),
            "elevation_gain_m": round(self.elevation_gain_m, 3),
            "elevation_loss_m": round(self.elevation_loss_m, 3),
            "since_departure_s": round(self.since_departure_s, 3),
            "halt_s": round(self.halt_s, 3),
            "route_name": self.route_name,
        }


# --- cutting the track -----------------------------------------------------------


def long_halts(
    points: tuple[RoutePoint, ...],
    *,
    minimum_s: float = LONG_HALT_S,
    radius_m: float = HALT_RADIUS_M,
) -> list[tuple[datetime, datetime]]:
    """Stretches of at least `minimum_s` in which the ride got nowhere.

    Read by distance, not by speed: the ride is at one place while the
    track has advanced less than `radius_m`. That covers the bike at rest,
    the GPS jittering round a car park at walking pace, and the track
    falling silent indoors -- the museum the owner found the film full of
    left a handful of slow points and long gaps between them. A halt that
    touches the start or the end of the day is not a chapter of it; it is
    the rider not having set off yet, or having arrived.
    """
    halts: list[tuple[datetime, datetime]] = []
    count = len(points)
    if count < 2:
        return halts
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    start = 0
    reach = 0
    while start < count:
        reach = max(reach, start)
        while reach + 1 < count:
            moved = points[reach + 1].distance_from_start_m - points[start].distance_from_start_m
            elapsed = (points[reach + 1].timestamp - points[start].timestamp).total_seconds()
            if moved > radius_m + WALKING_MPS * elapsed:
                break
            reach += 1
        # A long stand banks allowance that the first minutes of riding
        # would spend; the halt ends where the riding starts, not there.
        first, last = start, reach
        while last > first and _pace(points[last - 1], points[last]) > WALKING_MPS * 2:
            last -= 1
        while first < last and _pace(points[first], points[first + 1]) > WALKING_MPS * 2:
            first += 1
        stayed = (points[last].timestamp - points[first].timestamp).total_seconds()
        if stayed >= minimum_s:
            began, ended = points[first].timestamp, points[last].timestamp
            touches_edge = (began - ride_start).total_seconds() < MIN_CHAPTER_S or (
                ride_end - ended
            ).total_seconds() < MIN_CHAPTER_S
            if not touches_edge:
                halts.append((began, ended))
            start = reach + 1
        else:
            start += 1
    return halts


def _pace(earlier: RoutePoint, later: RoutePoint) -> float:
    seconds = (later.timestamp - earlier.timestamp).total_seconds()
    if seconds <= 0:
        return 0.0
    return (later.distance_from_start_m - earlier.distance_from_start_m) / seconds


def passes(
    points: tuple[RoutePoint, ...], *, prominence_m: float = PASS_PROMINENCE_M
) -> list[datetime]:
    """Where the ride crossed a high point with real climbing on both sides.

    A candidate is the highest point of its own neighbourhood; it is a pass
    when the ride had climbed at least `prominence_m` from its lowest point
    so far, and descends as much afterwards. Passes closer together than a
    chapter's minimum length keep only the higher.
    """
    elevated = [(p.timestamp, p.elevation_m) for p in points if p.elevation_m is not None]
    count = len(elevated)
    if count < 3:
        return []
    heights = [h for _, h in elevated]
    stamps = [s for s, _ in elevated]
    before = [0.0] * count
    after = [0.0] * count
    running = heights[0]
    for i in range(count):
        before[i] = running
        running = min(running, heights[i])
    running = heights[-1]
    for i in range(count - 1, -1, -1):
        after[i] = running
        running = min(running, heights[i])
    half = timedelta(seconds=MIN_CHAPTER_S / 2)
    found: list[tuple[datetime, float]] = []
    for i in range(1, count - 1):
        height = heights[i]
        if height - before[i] < prominence_m or height - after[i] < prominence_m:
            continue
        lo = bisect_left(stamps, stamps[i] - half)
        hi = bisect_right(stamps, stamps[i] + half)
        if height < max(heights[lo:hi]):
            continue
        found.append((stamps[i], height))
    kept: list[tuple[datetime, float]] = []
    for stamp, height in sorted(found, key=lambda item: -item[1]):
        if all(abs((stamp - s).total_seconds()) >= MIN_CHAPTER_S for s, _ in kept):
            kept.append((stamp, height))
    return sorted(stamp for stamp, _ in kept)


def _aggregates(
    points: tuple[RoutePoint, ...], start: datetime, end: datetime
) -> tuple[float, float, float, float | None, float | None]:
    within = [p for p in points if start <= p.timestamp <= end]
    if len(within) < 2:
        return 0.0, 0.0, 0.0, None, None
    heights = [p.elevation_m for p in within if p.elevation_m is not None]
    gain, loss = gain_and_loss(heights)
    distance = max(0.0, within[-1].distance_from_start_m - within[0].distance_from_start_m)
    return (
        distance,
        gain,
        loss,
        (heights[0] if heights else None),
        (heights[-1] if heights else None),
    )


def _turning_deg_per_km(points: tuple[RoutePoint, ...], start: datetime, end: datetime) -> float:
    within = [p for p in points if start <= p.timestamp <= end]
    if len(within) < 3:
        return 0.0
    distance = max(1.0, within[-1].distance_from_start_m - within[0].distance_from_start_m)
    bearings: list[float] = []
    for a, b in zip(within, within[1:], strict=False):
        if b.distance_from_start_m - a.distance_from_start_m < 20.0:
            continue
        lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
        dlon = math.radians(b.longitude - a.longitude)
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        bearings.append(math.degrees(math.atan2(y, x)) % 360.0)
    turned = 0.0
    for a, b in zip(bearings, bearings[1:], strict=False):
        delta = abs(b - a) % 360.0
        turned += min(delta, 360.0 - delta)
    return turned / (distance / 1000.0)


def _mean_speed(points: tuple[RoutePoint, ...], start: datetime, end: datetime) -> float:
    within = [p for p in points if start <= p.timestamp <= end]
    if len(within) < 2:
        return 0.0
    seconds = (within[-1].timestamp - within[0].timestamp).total_seconds()
    return (within[-1].distance_from_start_m - within[0].distance_from_start_m) / max(1.0, seconds)


def segment_ride(
    points: tuple[RoutePoint, ...],
    *,
    hints: Mapping[datetime, str] | None = None,
    minimum_chapters: int = MIN_CHAPTERS,
    maximum_chapters: int = MAX_CHAPTERS,
    long_leg_s: float = LONG_LEG_S,
    scenic: Sequence[ScenicStretch] = (),
    target_chapters: int = TARGET_CHAPTERS,
    stop_minimum_s: float = LONG_HALT_S,
    short_stop_s: float = STOP_MIN_S,
    minimum_legs: int = MIN_LEGS,
    ferries: Sequence[FerryCrossing] = (),
) -> tuple[RideChapter, ...]:
    """Cut the day into legs, halt to halt, and name each one.

    The owner's frame (2026-09-06): a chapter is a stretch of the route --
    where the ride went from and to -- so the cuts are the long halts. Each
    leg runs from the end of one halt to the end of the next and carries
    the time the ride stood there, so the card can say "25 minutes here".
    A leg longer than `long_leg_s` is cut at a pass it crosses, or failing
    that in half, so a day without a stop still has a shape; a day with
    more legs than `maximum_chapters` folds its shortest into a neighbour.

    `hints` are the model's words about windows, keyed by the window's
    start on the ride's clock; a chapter takes the words of the windows
    inside it. They only choose between titles the track already allows.

    `scenic` are the day's runs along official scenic routes
    (app.scenic_routes): each becomes one chapter of its own, cut at its
    ends -- snapped to a halt or the day's end when one is within a short
    chapter of it -- and never cut again for length. The owner's fifth
    rule (2026-09-06): a scenic route is one chapter, named for the route.

    `ferries` are the day's crossings (app.ferries): each is a chapter of
    its own too, named for the ferry and marked as carried, not ridden.
    """
    if len(points) < 2:
        raise RideChapterError("a ride needs at least two track points to be cut")
    if not 1 <= minimum_chapters <= maximum_chapters:
        raise RideChapterError("the chapter bounds are nonsense")
    if long_leg_s <= 0:
        raise RideChapterError("a leg's length must be positive")
    if not minimum_chapters <= target_chapters <= maximum_chapters:
        raise RideChapterError("the chapter target must sit between the bounds")
    ride_start, ride_end = points[0].timestamp, points[-1].timestamp
    if ride_end <= ride_start:
        raise RideChapterError("a ride must cover a positive duration")

    halts = long_halts(points, minimum_s=stop_minimum_s)
    # Few cuts from the long halts: the longest short stops become cuts too.
    if len(halts) + 1 < minimum_legs:
        shorter = [
            (start, end)
            for start, end in long_halts(points, minimum_s=short_stop_s)
            if (start, end) not in halts
        ]
        shorter.sort(key=lambda span: (span[0] - span[1]).total_seconds())
        while shorter and len(halts) + 1 < minimum_legs:
            halts.append(shorter.pop(0))
        halts.sort()
    stood = {end: (end - start).total_seconds() for start, end in halts}
    fixed = sorted({ride_start, ride_end, *(end for end in stood if ride_start < end < ride_end)})
    margin = timedelta(seconds=MIN_CHAPTER_S)

    def snapped(when: datetime) -> datetime:
        """A scenic end within a short chapter of a halt or the day's end takes that cut."""
        nearest = min(fixed, key=lambda f: abs((f - when).total_seconds()))
        return nearest if abs((nearest - when).total_seconds()) < MIN_CHAPTER_S else when

    scenic_spans = {(snapped(s.start_time), snapped(s.end_time)): s.route for s in scenic}
    ferry_spans = {(f.start_time, f.end_time): f.name for f in ferries if f.end_time > f.start_time}
    # A stop inside a crossing is the queue and the deck, not a cut: the
    # crossing is one chapter from the terminal to the far shore.
    fixed = [when for when in fixed if not any(a < when < b for a, b in ferry_spans)]
    stood = {end: seconds for end, seconds in stood.items() if end in fixed}
    scenic_spans = {
        (a, b): name
        for (a, b), name in scenic_spans.items()
        if b > a and not any(x < a < y or x < b < y for x, y in ferry_spans)
    }
    scenic_spans.update(ferry_spans)
    boundaries = sorted({*fixed, *(t for span in scenic_spans for t in span)})
    spans: list[tuple[datetime, datetime]] = list(zip(boundaries, boundaries[1:], strict=False))
    crossings = passes(points)

    def route_of(span: tuple[datetime, datetime]) -> str | None:
        for (a, b), name in scenic_spans.items():
            if a <= span[0] and span[1] <= b:
                return name
        return None

    def cut(span: tuple[datetime, datetime]) -> list[tuple[datetime, datetime]]:
        """A long leg is cut at the pass nearest its middle, else into even parts."""
        a, b = span
        length = (b - a).total_seconds()
        if route_of(span) is not None:
            return [span]
        if length <= long_leg_s or length < 2 * MIN_CHAPTER_S:
            return [span]
        middle = a + (b - a) / 2
        inside = [p for p in crossings if a + margin <= p <= b - margin]
        if inside:
            at = min(inside, key=lambda p: abs((p - middle).total_seconds()))
            return cut((a, at)) + cut((at, b))
        parts = math.ceil(length / long_leg_s)
        marks = [a + (b - a) * i / parts for i in range(parts + 1)]
        return list(zip(marks, marks[1:], strict=False))

    # A day with stops is cut at them and nowhere else for length; only a
    # day ridden straight through is cut into even parts.
    if not stood:
        spans = [piece for span in spans for piece in cut(span)]

    def halve_longest() -> bool:
        plain = [i for i in range(len(spans)) if route_of(spans[i]) is None]
        if not plain:
            return False
        longest = max(plain, key=lambda i: spans[i][1] - spans[i][0])
        a, b = spans[longest]
        if (b - a).total_seconds() < 2 * MIN_CHAPTER_S:
            return False
        middle = a + (b - a) / 2
        inside = [p for p in crossings if a + margin <= p <= b - margin]
        at = min(inside, key=lambda p: abs((p - middle).total_seconds())) if inside else middle
        spans[longest : longest + 1] = [(a, at), (at, b)]
        return True

    def merge_shortest() -> bool:
        if len(spans) < 2:
            return False
        plain = [i for i in range(len(spans)) if route_of(spans[i]) is None]
        shortest = min(plain or range(len(spans)), key=lambda i: spans[i][1] - spans[i][0])
        neighbours = [j for j in (shortest - 1, shortest + 1) if 0 <= j < len(spans)]
        other = min(neighbours, key=lambda j: spans[j][1] - spans[j][0])
        lo, hi = sorted((shortest, other))
        spans[lo] = (spans[lo][0], spans[hi][1])
        del spans[hi]
        return True

    # No stop at all: cut the longest plain legs until the day has about
    # five parts, so a day ridden straight through still has a shape.
    while not stood and len(spans) < target_chapters and halve_longest():
        pass
    while len(spans) < minimum_chapters and halve_longest():
        pass
    while len(spans) > maximum_chapters and merge_shortest():
        pass

    words = hints or {}
    chapters: list[RideChapter] = []
    for index, (start, end) in enumerate(spans):
        distance, gain, loss, first_m, last_m = _aggregates(points, start, end)
        inside = " ".join(text.lower() for stamp, text in words.items() if start <= stamp < end)
        if route_of((start, end)) in set(ferry_spans.values()):
            character = GapCharacter.FERRY
        else:
            character = _character(
                points,
                start,
                end,
                is_first=index == 0,
                is_last=index == len(spans) - 1,
                ends_at_pass=any(abs((end - p).total_seconds()) < 1.0 for p in crossings),
                gain=gain,
                loss=loss,
                distance=distance,
                heights=(first_m, last_m),
                words=inside,
            )
        chapters.append(
            RideChapter(
                start_time=start,
                end_time=end,
                character=character,
                distance_m=distance,
                elevation_gain_m=gain,
                elevation_loss_m=loss,
                start_elevation_m=first_m,
                end_elevation_m=last_m,
                since_departure_s=(start - ride_start).total_seconds(),
                halt_s=stood.get(end, 0.0),
                route_name=route_of((start, end)),
            )
        )
    return tuple(chapters)


def _character(
    points: tuple[RoutePoint, ...],
    start: datetime,
    end: datetime,
    *,
    is_first: bool,
    is_last: bool,
    ends_at_pass: bool,
    gain: float,
    loss: float,
    distance: float,
    heights: tuple[float | None, float | None],
    words: str,
) -> GapCharacter:
    # What the leg was like comes before where it sat in the day: the
    # day's ends are said by the fixed shots (app.fixed_shots), and a first
    # leg that climbed to a pass is the pass.
    net = gain - loss
    if ends_at_pass and net >= NET_ELEVATION_M:
        return GapCharacter.PASS
    if net >= NET_ELEVATION_M:
        return GapCharacter.CLIMB
    if net <= -NET_ELEVATION_M:
        return GapCharacter.DESCENT
    if any(word in words for word in _COAST_WORDS):
        return GapCharacter.COAST
    # The model's "urban" words no longer make a leg a town: on day 1 they
    # named a highway leg "街へ". Towns are sections (app.town_passages).
    within = [
        p.elevation_m for p in points if start <= p.timestamp <= end and p.elevation_m is not None
    ]
    if within and max(within) <= LOWLAND_M and distance >= LOWLAND_MIN_DISTANCE_M:
        return GapCharacter.COAST
    if _turning_deg_per_km(points, start, end) >= WINDING_DEG_PER_KM:
        return GapCharacter.WINDING
    if _mean_speed(points, start, end) >= FAST_MPS:
        return GapCharacter.LONG_HAUL
    if is_first:
        return GapCharacter.DEPARTURE
    if is_last:
        return GapCharacter.ARRIVAL
    return GapCharacter.LINK


# --- naming the chapters ---------------------------------------------------------

# Each character has a few titles, so that a day with two climbs does not
# say the same thing twice. The first is the plain one.
_TITLES: dict[StoryOutputLanguage, dict[GapCharacter, tuple[str, ...]]] = {
    StoryOutputLanguage.JAPANESE: {
        GapCharacter.DEPARTURE: ("出発", "走り出す"),
        GapCharacter.CLIMB: ("登りが続く", "さらに高く", "もう一度登る"),
        GapCharacter.PASS: ("峠を越える", "稜線へ", "次の峠"),
        GapCharacter.DESCENT: ("長い下り", "谷へ下る", "また下る"),
        GapCharacter.COAST: ("水辺を走る", "海沿いへ", "岸に沿って"),
        GapCharacter.WINDING: ("曲がりくねった道", "カーブが続く", "また曲がる"),
        GapCharacter.LONG_HAUL: ("走り続ける", "距離を稼ぐ", "まっすぐ先へ"),
        GapCharacter.TOWN: ("町を抜ける", "街へ", "次の町"),
        GapCharacter.HALT: ("ここで休む", "もう一度止まる", "三度目の休憩"),
        GapCharacter.FERRY: ("フェリーで渡る", "また船に乗る"),
        GapCharacter.ARRIVAL: ("到着へ", "帰り着く"),
        GapCharacter.LINK: ("先へ", "道が変わる", "その先"),
    },
    StoryOutputLanguage.ENGLISH: {
        GapCharacter.DEPARTURE: ("Setting off", "On the road"),
        GapCharacter.CLIMB: ("Climbing", "Higher still", "Climbing again"),
        GapCharacter.PASS: ("Over the pass", "To the ridge", "The next pass"),
        GapCharacter.DESCENT: ("The long descent", "Down to the valley", "Down again"),
        GapCharacter.COAST: ("Along the water", "To the coast", "Following the shore"),
        GapCharacter.WINDING: ("A road that turns", "Curve after curve", "Turning again"),
        GapCharacter.LONG_HAUL: ("Riding on", "Making distance", "Straight ahead"),
        GapCharacter.TOWN: ("Through town", "Into the streets", "The next town"),
        GapCharacter.HALT: ("A stop here", "Stopping again", "A third stop"),
        GapCharacter.FERRY: ("By ferry", "Aboard again"),
        GapCharacter.ARRIVAL: ("Arriving", "Home"),
        GapCharacter.LINK: ("Onward", "The road changes", "Further on"),
    },
}


def leg_places(start: PlaceName, end: PlaceName) -> tuple[str | None, str | None]:
    """The two names a leg's title uses: the towns, or the finer names inside one town.

    The owner's day-3 note (2026-09-07): a title repeating one city's name
    on both sides says nothing; a leg from a lookout to the ferry terminal
    inside one city is named by the suburb or the spot at each end, where
    the service gave one.
    """
    if start.place and start.place == end.place:
        finer_start, finer_end = _plain_place(start.finer), _plain_place(end.finer)
        if finer_start != finer_end and (finer_start != start.place or finer_end != end.place):
            return finer_start, finer_end
        if finer_start and finer_start == finer_end:
            return finer_start, finer_start
    return start.place, end.place


def _plain_place(name: str | None) -> str | None:
    """A place name without the service's bracketed alternative in the local language."""
    if not name:
        return name
    return re.sub(r"\s*\([^)]*\)", "", name).strip() or name


def leg_title(
    from_place: str | None, to_place: str | None, language: StoryOutputLanguage
) -> str | None:
    """Where the leg went from and to, or None when neither end has a name."""
    japanese = language is StoryOutputLanguage.JAPANESE
    if from_place and to_place:
        return from_place if from_place == to_place else f"{from_place} → {to_place}"
    if from_place:
        return f"{from_place}から" if japanese else f"From {from_place}"
    if to_place:
        return f"{to_place}へ" if japanese else f"To {to_place}"
    return None


def chapter_cards(
    chapters: tuple[RideChapter, ...],
    *,
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    names: Sequence[tuple[PlaceName, PlaceName]] | None = None,
) -> tuple[GapChapterCard, ...]:
    """One card per chapter: a title used once, and a body the track proves.

    With `names` -- where each leg went from and to (app.place_names) --
    the title is the two places and the phrase for what the leg was like
    moves to the front of the body. Without them, or for a leg neither of
    whose ends could be named, the phrase stays the title as before.
    """
    language = StoryOutputLanguage(output_language)
    used: dict[GapCharacter, int] = {}
    cards: list[GapChapterCard] = []
    for index, chapter in enumerate(chapters):
        options = _TITLES[language][chapter.character]
        nth = used.get(chapter.character, 0)
        used[chapter.character] = nth + 1
        if chapter.route_name:
            # The road's own name says more than any phrase for its character.
            title = chapter.route_name
            used[chapter.character] = nth
        elif nth < len(options):
            title = options[nth]
        else:
            # A fourth climb has nothing new to say about climbing.
            spare = _TITLES[language][GapCharacter.LINK]
            fallback = used.get(GapCharacter.LINK, 0)
            used[GapCharacter.LINK] = fallback + 1
            title = spare[fallback] if fallback < len(spare) else f"{spare[-1]} {fallback + 1}"
        body = describe_chapter(chapter, language)
        if names is not None and index < len(names):
            placed = leg_title(*leg_places(names[index][0], names[index][1]), language)
            if placed is not None:
                # "出発 · ..." said "departure" for the first leg; the phrase
                # now leads, so the zero-minutes mark is dropped.
                for mark in ("出発 · ", "Departure · "):
                    if body.startswith(mark):
                        body = body[len(mark) :]
                body = f"{title} · {body}"
                title = placed
        kind = (
            JourneyGapKind.BEFORE_FIRST_CLIP
            if index == 0
            else JourneyGapKind.AFTER_LAST_CLIP
            if index == len(chapters) - 1
            else JourneyGapKind.BETWEEN_CLIPS
        )
        cards.append(
            GapChapterCard(
                kind=kind,
                character=chapter.character,
                title=title,
                body=body,
                screen_duration_s=CHAPTER_CARD_S,
                since_departure_s=chapter.since_departure_s,
                duration_s=chapter.duration_s,
            )
        )
    return tuple(cards)


def describe_chapter(chapter: RideChapter, language: StoryOutputLanguage) -> str:
    """How long since departure, how far, and how the ground changed."""
    japanese = language is StoryOutputLanguage.JAPANESE
    parts = [_since(chapter.since_departure_s, japanese)]
    if chapter.character is GapCharacter.HALT:
        minutes = int(chapter.duration_s // 60)
        parts.append(f"ここで{minutes}分" if japanese else f"{minutes} min here")
        return " · ".join(parts)
    if chapter.character is GapCharacter.FERRY:
        hours, minutes = divmod(int(chapter.duration_s // 60), 60)
        afloat = f"{hours}時間{minutes:02d}分" if hours else f"{minutes}分"
        if not japanese:
            afloat = f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
        parts.append(f"船で{afloat}" if japanese else f"{afloat} afloat")
        return " · ".join(parts)
    parts.append(_distance(chapter.distance_m, japanese))
    first, last = chapter.start_elevation_m, chapter.end_elevation_m
    if first is not None and last is not None and abs(last - first) >= ELEVATION_WORTH_STATING_M:
        parts.append(
            f"海抜{int(first)}m → {int(last)}m" if japanese else f"{int(first)} m → {int(last)} m"
        )
    elif max(chapter.elevation_gain_m, chapter.elevation_loss_m) >= ELEVATION_WORTH_STATING_M:
        gain, loss = int(chapter.elevation_gain_m), int(chapter.elevation_loss_m)
        parts.append(f"登り{gain}m / 下り{loss}m" if japanese else f"+{gain} m / -{loss} m")
    if chapter.halt_s >= 60.0:
        minutes = int(chapter.halt_s // 60)
        parts.append(f"ここで{minutes}分" if japanese else f"{minutes} min here")
    return " · ".join(parts)


def _since(seconds: float, japanese: bool) -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if seconds < 60:
        return "出発" if japanese else "Departure"
    if japanese:
        return f"出発から{hours}時間{minutes:02d}分" if hours else f"出発から{minutes}分"
    return f"{hours} h {minutes:02d} min in" if hours else f"{minutes} min in"


def _distance(distance_m: float, japanese: bool) -> str:
    if distance_m >= 1_000:
        return f"{distance_m / 1000:.1f}km" if japanese else f"{distance_m / 1000:.1f} km"
    return f"{int(distance_m)}m" if japanese else f"{int(distance_m)} m"


# --- the timeline ----------------------------------------------------------------


def build_chapter_timeline(
    chapters: tuple[RideChapter, ...],
    footage: tuple[TimelineFootage, ...],
    points: tuple[RoutePoint, ...],
) -> StoryTimeline:
    """Each chapter opens with its card, then shows its windows in ride order.

    A card's ride span runs from the chapter's start to its first window,
    so the beats stay chronological and never overlap; a chapter with no
    window keeps its whole span. The card carries a gap segment with the
    chapter's aggregates, which is what the plan and the route map read.
    """
    if not chapters:
        raise RideChapterError("a timeline needs at least one chapter")
    ordered = sorted(footage, key=lambda item: item.start_time)
    beats: list[StoryBeat] = []
    cursor: datetime | None = None
    for index, chapter in enumerate(chapters):
        inside = [
            clip for clip in ordered if chapter.start_time <= clip.start_time < chapter.end_time
        ]
        card_start = chapter.start_time if cursor is None else max(chapter.start_time, cursor)
        card_end = inside[0].start_time if inside else chapter.end_time
        if card_end <= card_start:
            # The first window starts on the boundary: give the card the
            # second before it, which is still inside the previous chapter's
            # unfilmed tail.
            card_start = card_end - timedelta(seconds=1)
            if cursor is not None and card_start < cursor:
                raise RideChapterError("two windows leave no room for a chapter card")
        kind = (
            JourneyGapKind.BEFORE_FIRST_CLIP
            if index == 0
            else JourneyGapKind.AFTER_LAST_CLIP
            if index == len(chapters) - 1
            else JourneyGapKind.BETWEEN_CLIPS
        )
        beats.append(
            StoryBeat(
                kind=StoryBeatKind.GAP_CARD,
                ride_start_time=card_start,
                ride_end_time=card_end,
                screen_duration_s=CHAPTER_CARD_S,
                gap=JourneyGapSegment(
                    kind=kind,
                    start_time=card_start,
                    end_time=card_end,
                    distance_m=chapter.distance_m,
                    elevation_gain_m=chapter.elevation_gain_m,
                    elevation_loss_m=chapter.elevation_loss_m,
                ),
            )
        )
        cursor = card_end
        for clip in inside:
            beats.append(
                StoryBeat(
                    kind=StoryBeatKind.FOOTAGE,
                    ride_start_time=clip.start_time,
                    ride_end_time=clip.end_time,
                    screen_duration_s=clip.duration_s,
                    event_id=clip.event_id,
                    source_offset_s=clip.source_offset_s,
                )
            )
            cursor = clip.end_time
    try:
        return StoryTimeline(tuple(beats))
    except ValueError as error:
        raise RideChapterError(str(error)) from error


def day_account(points: tuple[RoutePoint, ...]) -> tuple[float, float, float, float]:
    """Distance, duration, climb and descent of the whole day, jitter removed."""
    if len(points) < 2:
        raise RideChapterError("a day needs at least two track points")
    distance = max(0.0, points[-1].distance_from_start_m - points[0].distance_from_start_m)
    duration = (points[-1].timestamp - points[0].timestamp).total_seconds()
    gain, loss = gain_and_loss(p.elevation_m for p in points)
    return distance, duration, gain, loss
