"""Give each uncovered stretch of the ride something honest to say on screen.

Gate 2 of docs/completion-roadmap-ja.md, third step. `app.journey_gaps`
established what the uncovered stretches are and `app.story_timeline` placed
them in the ride's order; this module writes the card the viewer actually
reads, and decides how long the film holds it.

Every word on a gap card comes from the GPS track alone — how long the ride
continued, how far it went, how much it climbed or descended. No place name,
no weather, no guess about what the rider saw. The camera was not running,
and the card says only what the ride itself proves. That is what lets the
film cross an unfilmed stretch without inventing one.

A card is held for the length `app.story_timeline` gave it, which follows
the riding it stands for. Nothing here stretches it to reach a target.

An earlier version did: when the confirmed footage fell short of a target
duration, the cards were held longer to make up the difference. That existed
to work around too little footage being accepted, and the 2026-09-03 design
review removed its premise — the film's length follows its material, and the
answer to a short film is to accept more of the ride, not to hold its cards
longer. Padding a film to a number was making the shortfall harder to see.

Card text is written to be shown, so it holds no identifier: no coordinate,
absolute capture time, event ID, asset ID, path, or file name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.agents.story_planner import StoryOutputLanguage
from app.journey_gaps import JourneyGapKind, JourneyGapSegment
from app.story_timeline import StoryTimeline

GAP_CHAPTER_SCHEMA_VERSION = "gap-chapter-plan-v1"

# Net elevation past this reads as a climb or a descent rather than as level
# ground with undulation.
_NET_ELEVATION_M = 150.0
# Past this distance the stretch's character is the distance itself.
_LONG_HAUL_M = 30_000.0
# Below this, elevation is not worth a clause on the card.
_ELEVATION_WORTH_STATING_M = 10.0


class GapCharacter(StrEnum):
    """What the GPS track says this stretch of riding was like."""

    DEPARTURE = "departure"
    ARRIVAL = "arrival"
    CLIMB = "climb"
    DESCENT = "descent"
    LONG_HAUL = "long_haul"
    LINK = "link"
    # Chapter characters (app.ride_chapters): what a stretch of the day was,
    # read off the track and the model's words, rather than what a gap was.
    PASS = "pass"
    COAST = "coast"
    WINDING = "winding"
    TOWN = "town"
    HALT = "halt"
    # A crossing on a ferry (app.ferries): carried, not ridden.
    FERRY = "ferry"
    # Framing cards (app.story_opening): the day's headline after the cold
    # open, and the closing account.
    HEADLINE = "headline"
    CLOSE = "close"


class GapChapterError(ValueError):
    """Raised when chapter cards or their durations cannot be built safely."""


@dataclass(frozen=True)
class GapChapterCard:
    """One card the viewer reads while the film crosses an unfilmed stretch."""

    kind: JourneyGapKind
    character: GapCharacter
    title: str
    body: str
    screen_duration_s: float
    # Where the card sits on the ride's clock: seconds after departure, and
    # for how long. Durations only -- no timestamp -- so the drawing of the
    # route can pick out the chapter's real stretch, and a halt its point.
    since_departure_s: float | None = None
    duration_s: float | None = None
    # A small line above the title -- "Day 3" on a multi-day trip.
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.title or not self.body:
            raise ValueError("a gap chapter card needs a title and a body")
        if self.label is not None and not self.label.strip():
            raise ValueError("a card's label, when given, says something")
        if self.screen_duration_s <= 0:
            raise ValueError("a gap chapter card must be held on screen")
        if (self.since_departure_s is None) != (self.duration_s is None):
            raise ValueError("a card on the ride's clock says both when it began and how long")
        if self.since_departure_s is not None and self.duration_s is not None:
            if self.since_departure_s < 0 or self.duration_s <= 0:
                raise ValueError("a card's place on the ride's clock must be a positive span")

    @property
    def is_on_the_clock(self) -> bool:
        """Whether the card knows where in the ride its chapter was."""
        return self.since_departure_s is not None and self.duration_s is not None

    def to_dict(self) -> dict[str, object]:
        """Written to be shown: aggregates and text, no identifier."""
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "character": self.character.value,
            "title": self.title,
            "body": self.body,
            "screen_duration_s": round(self.screen_duration_s, 3),
        }
        if self.since_departure_s is not None and self.duration_s is not None:
            payload["since_departure_s"] = round(self.since_departure_s, 3)
            payload["duration_s"] = round(self.duration_s, 3)
        if self.label is not None:
            payload["label"] = self.label
        return payload


@dataclass(frozen=True)
class GapChapterPlan:
    """Every gap card of one film, and what the film comes to."""

    cards: tuple[GapChapterCard, ...]
    footage_screen_duration_s: float
    total_screen_duration_s: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": GAP_CHAPTER_SCHEMA_VERSION,
            "card_count": len(self.cards),
            "footage_screen_duration_s": round(self.footage_screen_duration_s, 3),
            "total_screen_duration_s": round(self.total_screen_duration_s, 3),
            "cards": [card.to_dict() for card in self.cards],
        }


_TITLES: dict[StoryOutputLanguage, dict[GapCharacter, str]] = {
    StoryOutputLanguage.JAPANESE: {
        GapCharacter.DEPARTURE: "旅の始まり",
        GapCharacter.ARRIVAL: "帰り着くまで",
        GapCharacter.CLIMB: "登りが続く",
        GapCharacter.DESCENT: "下りへ",
        GapCharacter.LONG_HAUL: "走り続ける",
        GapCharacter.LINK: "道はつづく",
        GapCharacter.PASS: "峠を越える",
        GapCharacter.COAST: "水辺を走る",
        GapCharacter.WINDING: "曲がりくねった道",
        GapCharacter.TOWN: "町を抜ける",
        GapCharacter.HALT: "ここで休む",
        GapCharacter.HEADLINE: "この日",
        GapCharacter.CLOSE: "今日はここまで",
    },
    StoryOutputLanguage.ENGLISH: {
        GapCharacter.DEPARTURE: "The ride begins",
        GapCharacter.ARRIVAL: "The road home",
        GapCharacter.CLIMB: "Climbing on",
        GapCharacter.DESCENT: "Down the other side",
        GapCharacter.LONG_HAUL: "Riding onward",
        GapCharacter.LINK: "The road continues",
        GapCharacter.PASS: "Over the pass",
        GapCharacter.COAST: "Along the water",
        GapCharacter.WINDING: "A road that turns",
        GapCharacter.TOWN: "Through town",
        GapCharacter.HALT: "A stop here",
        GapCharacter.HEADLINE: "The day",
        GapCharacter.CLOSE: "That was the day",
    },
}


def classify_gap(segment: JourneyGapSegment) -> GapCharacter:
    """Name this stretch from its own aggregates.

    For the first and last stretches, where the stretch sits in the journey
    is the more telling fact than its terrain, so departure and arrival win
    over climb or distance. Everywhere in between, the terrain decides.
    """
    if segment.kind is JourneyGapKind.BEFORE_FIRST_CLIP:
        return GapCharacter.DEPARTURE
    if segment.kind is JourneyGapKind.AFTER_LAST_CLIP:
        return GapCharacter.ARRIVAL
    net = segment.elevation_gain_m - segment.elevation_loss_m
    if net >= _NET_ELEVATION_M:
        return GapCharacter.CLIMB
    if net <= -_NET_ELEVATION_M:
        return GapCharacter.DESCENT
    if segment.distance_m >= _LONG_HAUL_M:
        return GapCharacter.LONG_HAUL
    return GapCharacter.LINK


def describe_gap(segment: JourneyGapSegment, language: StoryOutputLanguage) -> str:
    """State what the track proves: how long, how far, and how much climbing."""
    japanese = language is StoryOutputLanguage.JAPANESE
    parts = [
        _format_duration(segment.duration_s, japanese),
        _format_distance(segment.distance_m, japanese),
    ]
    gain_m, loss_m = segment.elevation_gain_m, segment.elevation_loss_m
    if max(gain_m, loss_m) >= _ELEVATION_WORTH_STATING_M:
        parts.append(_format_elevation(gain_m, loss_m, japanese))
    return " · ".join(parts)


def build_gap_chapter_plan(
    timeline: StoryTimeline,
    *,
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
) -> GapChapterPlan:
    """Write the card for every uncovered stretch, at the length it was given.

    Card durations come from the timeline, where they already follow the
    riding each stands for. Nothing is stretched here: the film is as long as
    its material, and a film that feels short is telling you the selection was
    too strict, not that the cards should be held longer.
    """
    language = StoryOutputLanguage(output_language)
    gap_beats = timeline.gap_beats
    if any(beat.gap is None for beat in gap_beats):
        raise GapChapterError("a gap beat without its segment cannot be described")

    cards = tuple(
        GapChapterCard(
            kind=beat.gap.kind,
            character=classify_gap(beat.gap),
            title=_TITLES[language][classify_gap(beat.gap)],
            body=describe_gap(beat.gap, language),
            screen_duration_s=beat.screen_duration_s,
        )
        for beat in gap_beats
    )
    return GapChapterPlan(
        cards=cards,
        footage_screen_duration_s=timeline.footage_screen_duration_s,
        total_screen_duration_s=timeline.total_screen_duration_s,
    )


def _format_duration(duration_s: float, japanese: bool) -> str:
    minutes = int(duration_s // 60)
    hours, minutes = divmod(minutes, 60)
    if hours and japanese:
        return f"{hours}時間{minutes}分"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes}分" if japanese else f"{minutes} min"


def _format_distance(distance_m: float, japanese: bool) -> str:
    if distance_m >= 1_000:
        kilometres = distance_m / 1_000
        return f"{kilometres:.1f}km" if japanese else f"{kilometres:.1f} km"
    return f"{int(distance_m)}m" if japanese else f"{int(distance_m)} m"


def _format_elevation(gain_m: float, loss_m: float, japanese: bool) -> str:
    if japanese:
        return f"登り{int(gain_m)}m / 下り{int(loss_m)}m"
    return f"+{int(gain_m)} m / -{int(loss_m)} m"
