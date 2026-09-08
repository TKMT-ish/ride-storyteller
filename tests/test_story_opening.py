"""Tests for opening a film on its highlights and closing on the day's account."""

from __future__ import annotations

import pytest

from app.agents import StoryOutputLanguage
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_opening import HIGHLIGHT_COUNT, HIGHLIGHT_S, StoryOpeningError, frame_the_film
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind


def _card(title: str) -> StoryPlanBeat:
    return StoryPlanBeat(
        kind=StoryBeatKind.GAP_CARD,
        screen_duration_s=6.0,
        card=GapChapterCard(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            character=GapCharacter.LINK,
            title=title,
            body="x",
            screen_duration_s=6.0,
        ),
    )


def _clip(name: str, seconds: float = 12.0) -> StoryPlanBeat:
    return StoryPlanBeat(kind=StoryBeatKind.FOOTAGE, screen_duration_s=seconds, event_id=name)


def _plan(
    *beats: StoryPlanBeat, language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE
) -> JourneyStoryPlan:
    footage = sum(b.screen_duration_s for b in beats if b.kind is StoryBeatKind.FOOTAGE)
    return JourneyStoryPlan(
        beats=tuple(beats),
        output_language=language,
        footage_screen_duration_s=footage,
        total_screen_duration_s=sum(b.screen_duration_s for b in beats),
    )


_DAY = {
    "distance_m": 412_500.0,
    "duration_s": 8 * 3600 + 31 * 60,
    "elevation_gain_m": 3921.0,
    "elevation_loss_m": 4286.0,
}


def test_the_four_best_windows_open_the_film_short_and_in_ride_order() -> None:
    """The owner's day-1 note: four short highlights, then the first chapter's card."""
    plan = _plan(
        _card("A"), _clip("a1"), _clip("a2"), _card("B"), _clip("b1"), _clip("b2"), _clip("b3")
    )

    framed = frame_the_film(plan, preference={"a1": 5, "a2": 1, "b1": 3, "b2": 2, "b3": 4}, **_DAY)

    opening = framed.beats[:HIGHLIGHT_COUNT]
    assert [b.event_id for b in opening] == ["a2", "b1", "b2", "b3"]
    assert all(b.highlight and b.screen_duration_s == HIGHLIGHT_S for b in opening)
    first_card = framed.beats[HIGHLIGHT_COUNT]
    assert first_card.card is not None and first_card.card.title == "A"
    # The highlights come back at full length in their own chapters.
    full = [b for b in framed.beats if b.event_id == "b1" and not b.highlight]
    assert len(full) == 1 and full[0].screen_duration_s == 12.0


def test_a_film_with_fewer_windows_than_highlights_opens_on_all_of_them() -> None:
    plan = _plan(_card("A"), _clip("a1"), _clip("a2"))

    framed = frame_the_film(plan, preference={"a1": 2, "a2": 1}, **_DAY)

    assert [b.event_id for b in framed.beats[:2]] == ["a1", "a2"]
    assert framed.beats[2].card is not None and framed.beats[2].card.title == "A"


def test_the_film_closes_on_the_account_after_the_last_picture() -> None:
    """The arrival is the last picture; the closing card follows it (the owner, point 6)."""
    plan = _plan(_card("A"), _clip("a1"), _card("B"), _clip("b1"), _clip("b2"), _clip("b3"))

    framed = frame_the_film(plan, preference={"a1": 1, "b1": 2, "b2": 3, "b3": 4}, **_DAY)

    assert framed.beats[-1].card is not None
    assert framed.beats[-1].card.character is GapCharacter.CLOSE
    assert framed.beats[-2].event_id == "b3" and not framed.beats[-2].highlight
    assert "412.5km" in framed.beats[-1].card.body
    assert "登り3921m" in framed.beats[-1].card.body


def test_the_closing_card_lists_the_whole_route_once_each() -> None:
    plan = _plan(_card("A"), _clip("a1"))

    framed = frame_the_film(
        plan,
        preference={"a1": 1},
        **_DAY,
        route_chain=("Harbourton", "Vinefield", "Vinefield", "Kōwhai Bay", "Stonebridge"),
    )

    body = framed.beats[-1].card.body
    assert body.startswith("Harbourton → Vinefield → Kōwhai Bay → Stonebridge\n")


def test_the_totals_follow_the_beats_highlights_included() -> None:
    plan = _plan(_card("A"), _clip("a1"), _clip("a2"), _card("B"), _clip("b1"), _clip("b2"))

    framed = frame_the_film(plan, preference={"a1": 1, "a2": 2, "b1": 3, "b2": 4}, **_DAY)

    assert framed.footage_screen_duration_s == 48.0 + 4 * HIGHLIGHT_S
    assert framed.total_screen_duration_s == 48.0 + 4 * HIGHLIGHT_S + 6.0 * 3


def test_a_halted_window_is_not_a_highlight_while_moving_ones_exist() -> None:
    """The film pushes halted windows behind moving ones in the preference it passes."""
    plan = _plan(_card("A"), _clip("museum"), _clip("road"))

    framed = frame_the_film(
        plan, preference={"museum": 1 + 10_000, "road": 7}, **_DAY, highlights=1
    )

    assert framed.beats[0].event_id == "road"


def test_the_day_label_goes_on_every_full_screen_card() -> None:
    plan = _plan(_card("A"), _clip("a1"), _card("B"), _clip("b1"))

    framed = frame_the_film(plan, preference={"a1": 1, "b1": 2}, **_DAY, label="Day 3")

    labels = [b.card.label for b in framed.beats if b.card is not None]
    assert labels == ["Day 3", "Day 3", "Day 3"]
    plain = frame_the_film(plan, preference={"a1": 1, "b1": 2}, **_DAY)
    assert all(b.card.label is None for b in plain.beats if b.card is not None)


def test_a_plan_without_footage_is_left_alone() -> None:
    plan = _plan(_card("A"))
    assert frame_the_film(plan, preference={}, **_DAY) is plan


def test_english_cards_read_in_english() -> None:
    plan = _plan(_card("A"), _clip("a1"), _clip("a2"), language=StoryOutputLanguage.ENGLISH)
    framed = frame_the_film(plan, preference={"a1": 1, "a2": 2}, **_DAY)

    assert framed.beats[-1].card is not None and framed.beats[-1].card.title == "That was the day"
    assert "+3921 m" in framed.beats[-1].card.body


def test_a_nonsense_account_or_opening_is_refused() -> None:
    plan = _plan(_card("A"), _clip("a1"))
    with pytest.raises(StoryOpeningError):
        frame_the_film(
            plan,
            preference={"a1": 1},
            distance_m=1.0,
            duration_s=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
        )
    with pytest.raises(StoryOpeningError):
        frame_the_film(plan, preference={"a1": 1}, **_DAY, highlight_s=0.0)


def test_the_pickers_choice_opens_the_film_in_ride_order() -> None:
    plan = _plan(_card("A"), _clip("a1"), _clip("a2"), _card("B"), _clip("b1"), _clip("b2"))

    framed = frame_the_film(
        plan, preference={}, **_DAY, highlight_ids=("b2", "a1", "zz"), highlight_s=1.0
    )

    assert [b.event_id for b in framed.beats[:2]] == ["a1", "b2"]
    assert all(b.highlight and b.screen_duration_s == 1.0 for b in framed.beats[:2])
