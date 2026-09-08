"""Synthetic-fixture tests for laying a chapter's title over its first window (E-4).

Held: a chapter card followed by a window becomes that window carrying the
card; the title stays up five seconds at most and leaves the window's end
clean; the headline and the close stay full-screen; a chapter with no
window after it keeps its card; and the plan's totals follow.
"""

from __future__ import annotations

from app.agents import StoryOutputLanguage
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind
from app.story_titles import LOWER_THIRD_S, title_over_footage


def _card(title: str, character: GapCharacter, hold_s: float = 6.0) -> StoryPlanBeat:
    return StoryPlanBeat(
        StoryBeatKind.GAP_CARD,
        hold_s,
        card=GapChapterCard(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            character=character,
            title=title,
            body="本文",
            screen_duration_s=hold_s,
        ),
    )


def _footage(event_id: str, hold_s: float) -> StoryPlanBeat:
    return StoryPlanBeat(StoryBeatKind.FOOTAGE, hold_s, event_id=event_id)


def _plan(*beats: StoryPlanBeat) -> JourneyStoryPlan:
    footage = sum(b.screen_duration_s for b in beats if b.kind is StoryBeatKind.FOOTAGE)
    return JourneyStoryPlan(
        beats=beats,
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=footage,
        total_screen_duration_s=sum(b.screen_duration_s for b in beats),
    )


def test_a_chapter_card_before_a_window_becomes_the_window_with_the_title_on_it() -> None:
    plan = _plan(
        _footage("open", 10.0),
        _card("この日", GapCharacter.HEADLINE, 10.0),
        _card("出発", GapCharacter.DEPARTURE),
        _footage("w-1", 8.0),
        _card("今日はここまで", GapCharacter.CLOSE),
    )

    laid = title_over_footage(plan)

    kinds = [b.kind for b in laid.beats]
    assert kinds == [
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
    ]
    titled = laid.beats[2]
    assert titled.is_titled_footage and titled.event_id == "w-1"
    assert titled.screen_duration_s == 8.0, "the window keeps its length"
    assert titled.card is not None and titled.card.title == "出発"
    assert titled.card.screen_duration_s == LOWER_THIRD_S
    assert laid.beats[1].card is not None and laid.beats[1].card.character is GapCharacter.HEADLINE
    assert laid.beats[3].kind is StoryBeatKind.GAP_CARD, "the close frames the day full-screen"


def test_the_title_leaves_a_clean_second_and_is_never_too_short_to_read() -> None:
    plan = _plan(
        _card("出発", GapCharacter.DEPARTURE),
        _footage("w-1", 5.5),
        _card("登る", GapCharacter.CLIMB),
        _footage("w-2", 3.5),
    )

    laid = title_over_footage(plan)

    first = laid.beats[0]
    assert first.is_titled_footage and first.card is not None
    assert first.card.screen_duration_s == 4.5, "5.5 s window: the title leaves the last second"
    assert laid.beats[1].kind is StoryBeatKind.GAP_CARD, (
        "a 3.5 s window cannot carry a readable title"
    )
    assert laid.beats[2].kind is StoryBeatKind.FOOTAGE and not laid.beats[2].is_titled_footage


def test_a_chapter_that_was_never_filmed_keeps_its_card() -> None:
    plan = _plan(
        _card("出発", GapCharacter.DEPARTURE),
        _card("峠へ", GapCharacter.PASS),
        _footage("w-1", 8.0),
    )

    laid = title_over_footage(plan)

    assert laid.beats[0].kind is StoryBeatKind.GAP_CARD, "no window follows it"
    assert laid.beats[1].is_titled_footage and laid.beats[1].card is not None
    assert laid.beats[1].card.title == "峠へ"


def test_the_totals_follow_the_beats_that_remain() -> None:
    plan = _plan(
        _footage("open", 10.0),
        _card("出発", GapCharacter.DEPARTURE),
        _footage("w-1", 8.0),
        _card("今日はここまで", GapCharacter.CLOSE),
    )

    laid = title_over_footage(plan)

    assert laid.footage_screen_duration_s == 18.0
    assert laid.total_screen_duration_s == 24.0, "the six-second card is no longer its own beat"
    assert laid.output_language is plan.output_language


def test_laying_titles_twice_changes_nothing_more() -> None:
    plan = _plan(_card("出発", GapCharacter.DEPARTURE), _footage("w-1", 8.0))

    once = title_over_footage(plan)

    assert title_over_footage(once) == once


def test_a_title_keeps_where_its_window_begins() -> None:
    plan = _plan(
        _card("出発", GapCharacter.DEPARTURE),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1", source_offset_s=4.0),
    )

    (titled,) = title_over_footage(plan).beats

    assert titled.is_titled_footage and titled.source_offset_s == 4.0
