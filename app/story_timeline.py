"""Lay one ride out as a single story: filmed moments and the travel between.

Gate 2 of docs/completion-roadmap-ja.md, second step. `app.journey_gaps`
established what the uncovered stretches of a ride are; this module places
them in order with the confirmed footage so the result reads as one journey
from departure to arrival rather than a pile of good clips.

The spine is chronological, because that is what makes an uncovered stretch
mean anything: a card that says the ride continued for another stretch only
makes sense between the two filmed moments it actually sits between. Scene
roles (Hook / Build-up / Climax / Resolution) stay in `app.director`'s own
contract and are not duplicated here.

Screen time is not ride time. A stretch of riding that took a long while
becomes a short card, not a long one, so the film keeps moving. The mapping
is deterministic and bounded: proportional to the ride time it stands for,
clamped to a floor and a ceiling, so no single card can run away with the
film and no card is too brief to read.

Footage beats carry the event ID needed to cut the clip, exactly as other
private artifacts in this project do. `to_dict()` is the safe view: kinds,
screen durations, and gap aggregates only — no event ID, asset ID, absolute
capture time, coordinate, path, or file name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.journey_gaps import JourneyGapPlan, JourneyGapSegment

STORY_TIMELINE_SCHEMA_VERSION = "story-timeline-v1"

DEFAULT_GAP_CARD_MINIMUM_S = 3.0
DEFAULT_GAP_CARD_MAXIMUM_S = 8.0
# A card stands for the ride time it covers, at roughly one screen second per
# four minutes ridden, before the floor and ceiling apply.
DEFAULT_GAP_CARD_RATIO = 1.0 / 240.0


class StoryBeatKind(StrEnum):
    FOOTAGE = "footage"
    GAP_CARD = "gap_card"


class StoryTimelineError(ValueError):
    """Raised when a timeline cannot be laid out safely."""


@dataclass(frozen=True)
class TimelineFootage:
    """One confirmed clip, placed by the ride time it was filmed at.

    The window is the clip's own filmed window on GPS time — where the cut
    starts and ends — not the window of the GPS event that motivated it. The
    two are far apart in practice: a turn event lasts a couple of seconds
    while the clip around it runs half a minute. Passing the event window
    instead understates the film's length and leaves the gap plan claiming
    the ride was uncovered while the camera was in fact running, so build
    both this and `covered_windows` in `app.journey_gaps` from the same
    clip windows.
    """

    event_id: str
    start_time: datetime
    end_time: datetime
    source_offset_s: float = 0.0
    """How far into the judged window this cut begins (E-2); the times above already include it."""

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("timeline footage requires an event ID")
        if self.source_offset_s < 0:
            raise ValueError("timeline footage cannot begin before its window")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("timeline footage times must be timezone-aware")
        if self.end_time <= self.start_time:
            raise ValueError("timeline footage must cover a positive duration")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


@dataclass(frozen=True)
class StoryBeat:
    """One thing the viewer sees: a filmed moment, or the travel between two."""

    kind: StoryBeatKind
    ride_start_time: datetime
    ride_end_time: datetime
    screen_duration_s: float
    event_id: str | None = None
    gap: JourneyGapSegment | None = None
    source_offset_s: float = 0.0

    def __post_init__(self) -> None:
        if self.screen_duration_s <= 0:
            raise ValueError("story beat screen duration must be positive")
        if self.ride_end_time <= self.ride_start_time:
            raise ValueError("story beat must cover a positive ride duration")
        if self.kind is StoryBeatKind.FOOTAGE:
            if not self.event_id or self.gap is not None:
                raise ValueError("a footage beat carries an event ID and no gap")
        elif self.gap is None or self.event_id is not None:
            raise ValueError("a gap card carries a gap and no event ID")

    @property
    def ride_duration_s(self) -> float:
        return (self.ride_end_time - self.ride_start_time).total_seconds()

    def to_dict(self) -> dict[str, object]:
        """Safe view: no event ID, capture time, coordinate, path, or file name."""
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "screen_duration_s": round(self.screen_duration_s, 3),
            "ride_duration_s": round(self.ride_duration_s, 3),
        }
        if self.gap is not None:
            payload["gap"] = self.gap.to_dict()
        return payload


@dataclass(frozen=True)
class StoryTimeline:
    """Every beat of one ride, in the order the viewer will see them."""

    beats: tuple[StoryBeat, ...]

    def __post_init__(self) -> None:
        if not self.beats:
            raise ValueError("a story timeline needs at least one beat")
        starts = [beat.ride_start_time for beat in self.beats]
        if starts != sorted(starts):
            raise ValueError("story beats must be chronological")
        for earlier, later in zip(self.beats, self.beats[1:], strict=False):
            if later.ride_start_time < earlier.ride_end_time:
                raise ValueError("story beats must not overlap in ride time")
        event_ids = [beat.event_id for beat in self.beats if beat.event_id is not None]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("a story timeline must not reuse one event")

    @property
    def footage_beats(self) -> tuple[StoryBeat, ...]:
        return tuple(beat for beat in self.beats if beat.kind is StoryBeatKind.FOOTAGE)

    @property
    def gap_beats(self) -> tuple[StoryBeat, ...]:
        return tuple(beat for beat in self.beats if beat.kind is StoryBeatKind.GAP_CARD)

    @property
    def total_screen_duration_s(self) -> float:
        return sum(beat.screen_duration_s for beat in self.beats)

    @property
    def footage_screen_duration_s(self) -> float:
        return sum(beat.screen_duration_s for beat in self.footage_beats)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": STORY_TIMELINE_SCHEMA_VERSION,
            "beat_count": len(self.beats),
            "footage_beat_count": len(self.footage_beats),
            "gap_beat_count": len(self.gap_beats),
            "total_screen_duration_s": round(self.total_screen_duration_s, 3),
            "footage_screen_duration_s": round(self.footage_screen_duration_s, 3),
            "beats": [beat.to_dict() for beat in self.beats],
        }


def gap_card_screen_duration_s(
    gap: JourneyGapSegment,
    *,
    minimum_s: float = DEFAULT_GAP_CARD_MINIMUM_S,
    maximum_s: float = DEFAULT_GAP_CARD_MAXIMUM_S,
    ratio: float = DEFAULT_GAP_CARD_RATIO,
) -> float:
    """Map ride time to screen time, bounded at both ends."""
    if minimum_s <= 0 or maximum_s < minimum_s or ratio <= 0:
        raise StoryTimelineError("gap card duration bounds are invalid")
    return min(maximum_s, max(minimum_s, gap.duration_s * ratio))


def build_story_timeline(
    footage: tuple[TimelineFootage, ...],
    gap_plan: JourneyGapPlan,
    *,
    minimum_gap_card_s: float = DEFAULT_GAP_CARD_MINIMUM_S,
    maximum_gap_card_s: float = DEFAULT_GAP_CARD_MAXIMUM_S,
    gap_card_ratio: float = DEFAULT_GAP_CARD_RATIO,
) -> StoryTimeline:
    """Interleave confirmed footage and uncovered stretches into one story.

    Both inputs are placed by the ride time they belong to, so the result
    plays in the order the ride happened. Footage keeps its own length;
    every uncovered stretch becomes one bounded card. Overlapping footage,
    a stretch that overlaps footage, or a reused event fails closed rather
    than producing a timeline that misrepresents the ride.
    """
    if not footage and not gap_plan.segments:
        raise StoryTimelineError("a story timeline needs footage or an uncovered stretch")

    beats = [
        StoryBeat(
            kind=StoryBeatKind.FOOTAGE,
            ride_start_time=clip.start_time,
            ride_end_time=clip.end_time,
            screen_duration_s=clip.duration_s,
            event_id=clip.event_id,
        )
        for clip in footage
    ]
    beats.extend(
        StoryBeat(
            kind=StoryBeatKind.GAP_CARD,
            ride_start_time=segment.start_time,
            ride_end_time=segment.end_time,
            screen_duration_s=gap_card_screen_duration_s(
                segment,
                minimum_s=minimum_gap_card_s,
                maximum_s=maximum_gap_card_s,
                ratio=gap_card_ratio,
            ),
            gap=segment,
        )
        for segment in gap_plan.segments
    )
    beats.sort(key=lambda beat: (beat.ride_start_time, beat.ride_end_time))
    try:
        return StoryTimeline(tuple(beats))
    except ValueError as error:
        raise StoryTimelineError(str(error)) from error
