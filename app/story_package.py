"""The one artifact that says what this ride's film actually is.

Gate 2 of docs/completion-roadmap-ja.md, final step. `app.journey_gaps`,
`app.story_timeline`, and `app.gap_chapters` each answer one question; this
joins their answers into a single ordered plan and writes it into the private
package beside the exports it was derived from.

Writing it down is what makes the rest of the system possible. Gate 1's
duration check reads only the package's own JSON — never the GPX, never
source video — so until the film's shape lived in the package, that check
could only see the confirmed footage and had to call a complete film too
short. Gate 3's renderer needs the same ordered list to cut against. One
written plan serves both, and both then agree on what the film is.

A footage beat names its event and nothing more: the cut itself stays in
`ride-storyteller-candidates.json`, so the frames to lift are described in
exactly one place and cannot drift. Because the plan carries event IDs it is
a private artifact like its neighbours — it belongs in the git-ignored
package, never in a public export, a browser payload, or a handoff note.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import mkstemp

from app.agents.story_planner import StoryOutputLanguage
from app.gap_chapters import GapChapterCard, GapCharacter, build_gap_chapter_plan
from app.journey_gaps import JourneyGapKind
from app.story_timeline import StoryBeatKind, StoryTimeline

JOURNEY_STORY_PLAN_SCHEMA_VERSION = "journey-story-plan-v2"

JOURNEY_STORY_PLAN_FILE_NAME = "journey-story-plan.json"

# Durations are written to this many decimals; the plan is built to match so
# that reading it back yields exactly what was planned.
_WRITTEN_DECIMALS = 3

# Those roundings leave residues far below a frame. Anywhere two parts of the
# system compare durations, they must agree within one, or they will disagree
# about one film.
DURATION_TOLERANCE_S = 1.0 / 30.0


class JourneyStoryPlanError(ValueError):
    """Raised when a story plan cannot be built, written, or trusted."""


@dataclass(frozen=True)
class SectionNote:
    """One line of story laid over a window for a few seconds: a section (節).

    The owner's frame (2026-09-06, point 8): the lower third says where the
    ride is now and where the story turns -- through a town, leaving the
    highway toward somewhere, onto a scenic route, at a stop. `kind` is a
    fixed word from app.story_sections; `text` is what is shown.
    """

    kind: str
    text: str
    screen_duration_s: float

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.text.strip():
            raise ValueError("a section note needs a kind and a text")
        if self.screen_duration_s <= 0:
            raise ValueError("a section note must stay up for some time")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "text": self.text,
            "screen_duration_s": round(self.screen_duration_s, 3),
        }


@dataclass(frozen=True)
class StoryPlanBeat:
    """One beat of the film: an event to cut, or a card to hold."""

    kind: StoryBeatKind
    screen_duration_s: float
    event_id: str | None = None
    source_offset_s: float = 0.0
    """Where inside the judged window this footage begins, in seconds.

    A twelve-second window is judged whole; the cut shows the half that
    moves more (E-2), so the beat says how far in to start. A card has none.
    """
    card: GapChapterCard | None = None
    """The card this beat shows.

    A gap beat is its card, held full-screen. A footage beat may carry one
    too: the chapter's title, laid over the window's lower third for the
    card's screen time while the picture keeps moving (E-4). Such a card's
    `screen_duration_s` is how long the title stays up, never longer than
    the window.
    """

    section: SectionNote | None = None
    """A section's line over this footage, after any title (app.story_sections)."""

    highlight: bool = False
    """A short taste of this window in the cold open; it comes back in full later."""

    def __post_init__(self) -> None:
        if self.screen_duration_s <= 0:
            raise ValueError("a story plan beat must be held on screen")
        if self.source_offset_s < 0:
            raise ValueError("a footage beat cannot begin before its window")
        if self.kind is StoryBeatKind.FOOTAGE:
            if not self.event_id:
                raise ValueError("a footage beat names an event")
            if self.card is not None and self.card.screen_duration_s > self.screen_duration_s:
                raise ValueError("a title over footage cannot outlast the window under it")
            if self.section is not None and self.section.screen_duration_s > self.screen_duration_s:
                raise ValueError("a section over footage cannot outlast the window under it")
            if self.highlight and (self.card is not None or self.section is not None):
                raise ValueError("a highlight is a bare taste of a window: no title, no section")
        elif self.card is None or self.event_id is not None or self.section is not None:
            raise ValueError("a gap beat carries a card and names no event")
        elif self.highlight:
            raise ValueError("only footage can be a highlight")

    @property
    def is_titled_footage(self) -> bool:
        """Footage with the chapter's title over it, rather than a card before it."""
        return self.kind is StoryBeatKind.FOOTAGE and self.card is not None

    def to_dict(self) -> dict[str, object]:
        """Private view: a footage beat names its event so the cut can be found."""
        payload: dict[str, object] = {
            "kind": self.kind.value,
            "screen_duration_s": round(self.screen_duration_s, 3),
        }
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        if self.source_offset_s:
            payload["source_offset_s"] = round(self.source_offset_s, 3)
        if self.card is not None:
            payload["card"] = self.card.to_dict()
        if self.section is not None:
            payload["section"] = self.section.to_dict()
        if self.highlight:
            payload["highlight"] = True
        return payload


@dataclass(frozen=True)
class JourneyStoryPlan:
    """Every beat of one ride's film, in order, with what it adds up to."""

    beats: tuple[StoryPlanBeat, ...]
    output_language: StoryOutputLanguage
    footage_screen_duration_s: float
    total_screen_duration_s: float

    def __post_init__(self) -> None:
        if not self.beats:
            raise ValueError("a story plan needs at least one beat")
        # A window is shown once in full; a highlight is a taste of it, allowed
        # once more at the start.
        event_ids = [b.event_id for b in self.beats if b.event_id is not None and not b.highlight]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("a story plan must not reuse one event")
        tastes = [b.event_id for b in self.beats if b.highlight]
        if len(tastes) != len(set(tastes)):
            raise ValueError("a window is tasted at most once")

    @property
    def footage_beats(self) -> tuple[StoryPlanBeat, ...]:
        return tuple(beat for beat in self.beats if beat.kind is StoryBeatKind.FOOTAGE)

    @property
    def card_beats(self) -> tuple[StoryPlanBeat, ...]:
        """Beats held as a full-screen card."""
        return tuple(beat for beat in self.beats if beat.kind is StoryBeatKind.GAP_CARD)

    @property
    def beats_with_cards(self) -> tuple[StoryPlanBeat, ...]:
        """Every beat that has a card to draw, full-screen or over footage, in order."""
        return tuple(beat for beat in self.beats if beat.card is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": JOURNEY_STORY_PLAN_SCHEMA_VERSION,
            "output_language": self.output_language.value,
            "footage_screen_duration_s": round(self.footage_screen_duration_s, 3),
            "total_screen_duration_s": round(self.total_screen_duration_s, 3),
            "beats": [beat.to_dict() for beat in self.beats],
        }


def build_journey_story_plan(
    timeline: StoryTimeline,
    *,
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    cards: tuple[GapChapterCard, ...] | None = None,
) -> JourneyStoryPlan:
    """Join the ride's order and its chapter cards into one plan.

    By default the cards come from `build_gap_chapter_plan`, one per
    uncovered stretch. A caller that cut the day into chapters instead
    (`app.ride_chapters`) passes its own cards, one per card beat and in
    the timeline's order; either way each card is placed on the beat it
    was written for and the footage keeps the durations the timeline gave
    it.
    """
    if cards is None:
        cards = build_gap_chapter_plan(timeline, output_language=output_language).cards
    if len(cards) != len(timeline.gap_beats):
        raise JourneyStoryPlanError("the plan needs exactly one card per card beat")
    cards = iter(cards)
    beats: list[StoryPlanBeat] = []
    for beat in timeline.beats:
        if beat.kind is StoryBeatKind.FOOTAGE:
            beats.append(
                StoryPlanBeat(
                    kind=StoryBeatKind.FOOTAGE,
                    screen_duration_s=_written_duration(beat.screen_duration_s),
                    event_id=beat.event_id,
                    source_offset_s=_written_duration(beat.source_offset_s),
                )
            )
            continue
        card = next(cards, None)
        if card is None:  # pragma: no cover - guarded by the chapter plan itself
            raise JourneyStoryPlanError("a gap beat has no chapter card")
        held = _written_duration(card.screen_duration_s)
        beats.append(
            StoryPlanBeat(
                kind=StoryBeatKind.GAP_CARD,
                screen_duration_s=held,
                card=replace(card, screen_duration_s=held),
            )
        )
    # Totals are summed from the durations that will actually be written, not
    # from the unrounded ones. A plan whose totals disagreed with its own beats
    # after a round trip would leave Gate 1 measuring a different film from the
    # one the renderer cuts.
    footage_total = sum(
        beat.screen_duration_s for beat in beats if beat.kind is StoryBeatKind.FOOTAGE
    )
    total = sum(beat.screen_duration_s for beat in beats)
    try:
        return JourneyStoryPlan(
            beats=tuple(beats),
            output_language=StoryOutputLanguage(output_language),
            footage_screen_duration_s=_written_duration(footage_total),
            total_screen_duration_s=_written_duration(total),
        )
    except ValueError as error:
        raise JourneyStoryPlanError(str(error)) from error


def _written_duration(seconds: float) -> float:
    """Round to what `to_dict` writes, so a plan round-trips unchanged."""
    return round(seconds, _WRITTEN_DECIMALS)


def load_journey_story_plan(path: Path) -> JourneyStoryPlan:
    """Read a plan back, rejecting anything this version cannot trust."""
    if path.is_symlink() or not path.is_file():
        raise JourneyStoryPlanError("journey story plan is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JourneyStoryPlanError("journey story plan is unreadable") from error
    if not isinstance(payload, dict):
        raise JourneyStoryPlanError("journey story plan is malformed")
    if payload.get("schema_version") != JOURNEY_STORY_PLAN_SCHEMA_VERSION:
        raise JourneyStoryPlanError("unsupported journey story plan schema")
    try:
        beats = tuple(_beat_from_dict(item) for item in payload["beats"])
        return JourneyStoryPlan(
            beats=beats,
            output_language=StoryOutputLanguage(payload["output_language"]),
            footage_screen_duration_s=float(payload["footage_screen_duration_s"]),
            total_screen_duration_s=float(payload["total_screen_duration_s"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise JourneyStoryPlanError("journey story plan is malformed") from error


def write_journey_story_plan(
    output_path: Path, plan: JourneyStoryPlan, *, overwrite: bool = True
) -> Path:
    """Persist the plan atomically.

    Derived data, so a rerun replaces it by default rather than leaving a
    stale film shape next to fresh exports.
    """
    if output_path.is_symlink():
        raise JourneyStoryPlanError("journey story plan path is unsafe")
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "journey story plan already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def _beat_from_dict(item: object) -> StoryPlanBeat:
    if not isinstance(item, dict):
        raise ValueError("a story plan beat is malformed")
    kind = StoryBeatKind(item["kind"])
    if kind is StoryBeatKind.FOOTAGE:
        return StoryPlanBeat(
            kind=kind,
            screen_duration_s=float(item["screen_duration_s"]),
            event_id=str(item["event_id"]),
            source_offset_s=float(item.get("source_offset_s", 0.0)),
            card=_card_from_dict(item["card"]) if item.get("card") is not None else None,
            section=(
                _section_from_dict(item["section"]) if item.get("section") is not None else None
            ),
            highlight=bool(item.get("highlight", False)),
        )
    return StoryPlanBeat(
        kind=kind,
        screen_duration_s=float(item["screen_duration_s"]),
        card=_card_from_dict(item["card"]),
    )


def _section_from_dict(section: object) -> SectionNote:
    if not isinstance(section, dict):
        raise ValueError("a section note is malformed")
    return SectionNote(
        kind=str(section["kind"]),
        text=str(section["text"]),
        screen_duration_s=float(section["screen_duration_s"]),
    )


def _card_from_dict(card: object) -> GapChapterCard:
    if not isinstance(card, dict):
        raise ValueError("a chapter card is malformed")
    return GapChapterCard(
        kind=JourneyGapKind(card["kind"]),
        character=GapCharacter(card["character"]),
        title=str(card["title"]),
        body=str(card["body"]),
        screen_duration_s=float(card["screen_duration_s"]),
        since_departure_s=_optional_float(card.get("since_departure_s")),
        duration_s=_optional_float(card.get("duration_s")),
        label=str(card["label"]) if card.get("label") else None,
    )


def _optional_float(value: object) -> float | None:
    """A plan written before cards knew their clock simply has no such field."""
    return None if value is None else float(value)
