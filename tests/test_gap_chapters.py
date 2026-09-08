"""Synthetic-fixture tests for gap chapter cards and duration allocation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.story_planner import StoryOutputLanguage
from app.gap_chapters import (
    GapChapterCard,
    GapCharacter,
    build_gap_chapter_plan,
    classify_gap,
    describe_gap,
)
from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_timeline import TimelineFootage, build_story_timeline

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _gap(
    start_offset_s: float,
    end_offset_s: float,
    kind: JourneyGapKind = JourneyGapKind.BETWEEN_CLIPS,
    *,
    distance_m: float = 1_000.0,
    gain_m: float = 10.0,
    loss_m: float = 5.0,
) -> JourneyGapSegment:
    return JourneyGapSegment(
        kind=kind,
        start_time=_at(start_offset_s),
        end_time=_at(end_offset_s),
        distance_m=distance_m,
        elevation_gain_m=gain_m,
        elevation_loss_m=loss_m,
    )


def _timeline(*, footage_count: int = 2, gap_count: int = 3):
    """A ride that alternates gap, footage, gap, footage, ... gap."""
    footage = tuple(
        TimelineFootage(
            event_id=f"evt_{index}",
            start_time=_at(3600.0 * (index + 1)),
            end_time=_at(3600.0 * (index + 1) + 30.0),
        )
        for index in range(footage_count)
    )
    gaps = []
    cursor = 0.0
    for index in range(gap_count):
        end = 3600.0 * (index + 1) if index < footage_count else cursor + 1800.0
        kind = (
            JourneyGapKind.BEFORE_FIRST_CLIP
            if index == 0
            else JourneyGapKind.AFTER_LAST_CLIP
            if index == gap_count - 1
            else JourneyGapKind.BETWEEN_CLIPS
        )
        gaps.append(_gap(cursor, end, kind))
        cursor = end + 30.0
    return build_story_timeline(footage, JourneyGapPlan(tuple(gaps)))


def test_first_and_last_stretches_are_named_by_position() -> None:
    assert (
        classify_gap(_gap(0.0, 600.0, JourneyGapKind.BEFORE_FIRST_CLIP, gain_m=900.0))
        is GapCharacter.DEPARTURE
    )
    assert (
        classify_gap(_gap(0.0, 600.0, JourneyGapKind.AFTER_LAST_CLIP, loss_m=900.0))
        is GapCharacter.ARRIVAL
    )


def test_middle_stretches_are_named_by_terrain() -> None:
    assert classify_gap(_gap(0.0, 600.0, gain_m=400.0, loss_m=20.0)) is GapCharacter.CLIMB
    assert classify_gap(_gap(0.0, 600.0, gain_m=20.0, loss_m=400.0)) is GapCharacter.DESCENT
    assert classify_gap(_gap(0.0, 600.0, distance_m=60_000.0)) is GapCharacter.LONG_HAUL
    assert classify_gap(_gap(0.0, 600.0)) is GapCharacter.LINK


def test_undulating_ground_is_not_a_climb() -> None:
    """Large gain and large loss that cancel out is level ground, not a climb."""
    assert classify_gap(_gap(0.0, 600.0, gain_m=800.0, loss_m=790.0)) is GapCharacter.LINK


def test_card_text_states_only_what_the_track_proves() -> None:
    segment = _gap(0.0, 6_720.0, distance_m=74_300.0, gain_m=620.0, loss_m=410.0)

    japanese = describe_gap(segment, StoryOutputLanguage.JAPANESE)
    english = describe_gap(segment, StoryOutputLanguage.ENGLISH)

    assert japanese == "1時間52分 · 74.3km · 登り620m / 下り410m"
    assert english == "1 h 52 min · 74.3 km · +620 m / -410 m"


def test_short_flat_stretch_omits_the_elevation_clause() -> None:
    segment = _gap(0.0, 300.0, distance_m=480.0, gain_m=2.0, loss_m=1.0)

    assert describe_gap(segment, StoryOutputLanguage.JAPANESE) == "5分 · 480m"
    assert describe_gap(segment, StoryOutputLanguage.ENGLISH) == "5 min · 480 m"


def test_both_languages_describe_the_same_structure() -> None:
    segment = _gap(0.0, 6_720.0, distance_m=74_300.0, gain_m=620.0, loss_m=410.0)

    japanese = describe_gap(segment, StoryOutputLanguage.JAPANESE)
    english = describe_gap(segment, StoryOutputLanguage.ENGLISH)

    assert japanese.count(" · ") == english.count(" · ") == 2


def test_serialized_plan_carries_no_private_detail() -> None:
    timeline = build_story_timeline(
        (
            TimelineFootage(
                event_id="evt_private_alpha", start_time=_at(3600.0), end_time=_at(3630.0)
            ),
        ),
        JourneyGapPlan((_gap(0.0, 3600.0, JourneyGapKind.BEFORE_FIRST_CLIP),)),
    )

    payload = build_gap_chapter_plan(timeline).to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["card_count"] == 1
    for forbidden in ("evt_private_alpha", "2026-05-01", "latitude", "longitude"):
        assert forbidden not in serialized
    assert set(payload["cards"][0]) == {
        "kind",
        "character",
        "title",
        "body",
        "screen_duration_s",
    }


def test_english_and_japanese_plans_match_in_structure() -> None:
    timeline = _timeline()

    japanese = build_gap_chapter_plan(timeline, output_language=StoryOutputLanguage.JAPANESE)
    english = build_gap_chapter_plan(timeline, output_language=StoryOutputLanguage.ENGLISH)

    assert [card.character for card in japanese.cards] == [card.character for card in english.cards]
    assert [card.screen_duration_s for card in japanese.cards] == pytest.approx(
        [card.screen_duration_s for card in english.cards]
    )
    assert all(
        japanese_card.title != english_card.title
        for japanese_card, english_card in zip(japanese.cards, english.cards, strict=True)
    )


def test_a_film_with_no_gaps_needs_no_cards() -> None:
    timeline = build_story_timeline(
        (TimelineFootage(event_id="evt_a", start_time=_at(0.0), end_time=_at(30.0)),),
        JourneyGapPlan(()),
    )

    plan = build_gap_chapter_plan(timeline)

    assert plan.cards == ()
    assert plan.total_screen_duration_s == pytest.approx(plan.footage_screen_duration_s)


def test_a_card_keeps_the_length_the_timeline_gave_it() -> None:
    """Nothing here stretches a card: the film is as long as its material."""
    timeline = _timeline()
    base = [beat.screen_duration_s for beat in timeline.gap_beats]

    plan = build_gap_chapter_plan(timeline)

    assert [card.screen_duration_s for card in plan.cards] == pytest.approx(base)
    assert plan.total_screen_duration_s == pytest.approx(timeline.total_screen_duration_s)
    assert plan.footage_screen_duration_s == pytest.approx(timeline.footage_screen_duration_s)


def test_a_card_with_half_a_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="clock"):
        GapChapterCard(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            character=GapCharacter.CLIMB,
            title="登り",
            body="本文",
            screen_duration_s=6.0,
            since_departure_s=100.0,
        )
    with pytest.raises(ValueError, match="positive span"):
        GapChapterCard(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            character=GapCharacter.CLIMB,
            title="登り",
            body="本文",
            screen_duration_s=6.0,
            since_departure_s=100.0,
            duration_s=0.0,
        )
