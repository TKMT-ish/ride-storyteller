"""Synthetic-fixture tests for the sections laid over windows inside a leg (点 8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.agents import StoryOutputLanguage
from app.chapter_card import build_section_html
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.scenic_routes import ScenicStretch
from app.story_package import JourneyStoryPlan, SectionNote, StoryPlanBeat, _beat_from_dict
from app.story_sections import (
    SECTION_S,
    SectionEvent,
    SectionKind,
    arrival_line,
    attach_sections,
    departure_line,
    halt_line,
    highway_entries,
    highway_exits,
    highway_off_line,
    highway_on_line,
    scenic_events,
    scenic_in_line,
    scenic_out_line,
    sections_of,
    stopover_line,
    town_line,
    with_clock,
)
from app.story_timeline import StoryBeatKind

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_JA = StoryOutputLanguage.JAPANESE
_EN = StoryOutputLanguage.ENGLISH


def _plan(*beats: StoryPlanBeat) -> JourneyStoryPlan:
    footage = sum(b.screen_duration_s for b in beats if b.kind is StoryBeatKind.FOOTAGE)
    return JourneyStoryPlan(
        beats=beats,
        output_language=_JA,
        footage_screen_duration_s=footage,
        total_screen_duration_s=sum(b.screen_duration_s for b in beats),
    )


def _window(name: str, seconds: float = 8.0, *, titled: bool = False) -> StoryPlanBeat:
    card = (
        GapChapterCard(
            kind=JourneyGapKind.BETWEEN_CLIPS,
            character=GapCharacter.LINK,
            title="先へ",
            body="出発から1時間",
            screen_duration_s=5.0,
        )
        if titled
        else None
    )
    return StoryPlanBeat(StoryBeatKind.FOOTAGE, seconds, event_id=name, card=card)


def _event(kind: SectionKind, minutes: float, text: str = "町を通る") -> SectionEvent:
    return SectionEvent(kind, _T0 + timedelta(minutes=minutes), text)


# --- laying a line on the nearest window --------------------------------------


def test_a_line_lands_on_the_window_nearest_its_moment() -> None:
    plan = _plan(_window("a"), _window("b"), _window("c"))
    starts = {"a": _T0, "b": _T0 + timedelta(minutes=5), "c": _T0 + timedelta(minutes=12)}

    laid = attach_sections(plan, (_event(SectionKind.TOWN, 4.6),), starts)

    carried = sections_of(laid)
    assert [b.event_id for b in carried] == ["b"]
    assert carried[0].section == SectionNote("town", "町を通る", SECTION_S)


def test_a_titled_window_and_a_far_window_do_not_carry_a_line() -> None:
    plan = _plan(_window("a", titled=True), _window("b"))
    starts = {"a": _T0 + timedelta(minutes=4), "b": _T0 + timedelta(minutes=30)}

    laid = attach_sections(plan, (_event(SectionKind.TOWN, 4.0),), starts)

    assert sections_of(laid) == ()


def test_one_window_carries_one_line_and_a_short_window_carries_none() -> None:
    plan = _plan(_window("a"), _window("b", seconds=3.0))
    starts = {"a": _T0, "b": _T0 + timedelta(minutes=10)}
    events = (_event(SectionKind.TOWN, 0.0, "A"), _event(SectionKind.HALT_PLACE, 0.5, "B"))

    laid = attach_sections(plan, events, starts)

    carried = sections_of(laid)
    assert [b.event_id for b in carried] == ["a"]
    assert carried[0].section is not None and carried[0].section.text == "A"
    short = attach_sections(plan, (_event(SectionKind.TOWN, 10.0, "C"),), starts)
    assert sections_of(short) == ()


def test_a_section_stays_up_no_longer_than_the_window_less_its_clean_tail() -> None:
    plan = _plan(_window("a", seconds=4.5))

    laid = attach_sections(plan, (_event(SectionKind.TOWN, 0.0),), {"a": _T0})

    assert sections_of(laid)[0].section.screen_duration_s == 3.5


def test_a_section_round_trips_through_the_plan_file_and_never_sits_on_a_card() -> None:
    beat = StoryPlanBeat(
        StoryBeatKind.FOOTAGE, 8.0, event_id="a", section=SectionNote("town", "町を通る", 4.0)
    )

    assert _beat_from_dict(json.loads(json.dumps(beat.to_dict()))) == beat
    with pytest.raises(ValueError):
        StoryPlanBeat(
            StoryBeatKind.FOOTAGE, 3.0, event_id="a", section=SectionNote("town", "x", 4.0)
        )
    with pytest.raises(ValueError):
        StoryPlanBeat(
            StoryBeatKind.GAP_CARD,
            6.0,
            card=GapChapterCard(
                kind=JourneyGapKind.BETWEEN_CLIPS,
                character=GapCharacter.LINK,
                title="t",
                body="b",
                screen_duration_s=6.0,
            ),
            section=SectionNote("town", "x", 4.0),
        )


# --- the lines ------------------------------------------------------------------


def test_the_lines_read_in_both_languages() -> None:
    assert town_line("Ashford", _JA) == "Ashfordを通る"
    assert town_line("Ashford", _EN) == "Through Ashford"
    assert halt_line("Bayford", 25, _JA) == "Bayfordで休憩 · 25分"
    assert halt_line(None, 25, _EN) == "Here · 25 min stop"
    assert stopover_line("Stonehaven", 8, _JA) == "Stonehavenに立ち寄る · 8分"
    assert scenic_in_line("Southern Scenic Route", _JA) == "Southern Scenic Routeに入る"
    assert scenic_out_line("Southern Scenic Route", _EN) == "Leaving the Southern Scenic Route"
    assert (
        highway_off_line("State Highway 1", "Kōwhai Bay", _JA)
        == "State Highway 1を離れ、Kōwhai Bayへ"
    )
    assert highway_off_line("State Highway 1", None, _EN) == "Off State Highway 1"


def test_the_section_page_carries_the_line_and_nothing_else() -> None:
    page = build_section_html("Ashfordを通る")

    assert "Ashfordを通る" in page
    assert "<img" not in page and "http" not in page
    with pytest.raises(ValueError):
        build_section_html("  ")


# --- the moments ----------------------------------------------------------------


def test_scenic_events_say_onto_and_off_except_at_the_days_ends() -> None:
    ride_start, ride_end = _T0, _T0 + timedelta(hours=6)
    inside = ScenicStretch("R", _T0 + timedelta(hours=1), _T0 + timedelta(hours=3))
    to_the_end = ScenicStretch("S", _T0 + timedelta(hours=4), ride_end - timedelta(minutes=2))

    events = scenic_events(
        (inside, to_the_end), ride_start=ride_start, ride_end=ride_end, language=_JA
    )

    assert [(e.kind, e.at) for e in events] == [
        (SectionKind.SCENIC_IN, inside.start_time),
        (SectionKind.SCENIC_OUT, inside.end_time),
        (SectionKind.SCENIC_IN, to_the_end.start_time),
    ]


def test_a_highway_exit_is_where_the_ride_stays_off_for_good() -> None:
    ride_end = _T0 + timedelta(hours=6)
    first = ScenicStretch("State Highway 1", _T0, _T0 + timedelta(hours=1))
    brief_gap = ScenicStretch(
        "State Highway 1", _T0 + timedelta(hours=1, minutes=5), _T0 + timedelta(hours=2)
    )
    later = ScenicStretch("State Highway 8", _T0 + timedelta(hours=3), _T0 + timedelta(hours=4))

    events = highway_exits(
        (first, brief_gap, later),
        ride_end=ride_end,
        toward={brief_gap.end_time: "Tekapo"},
        language=_JA,
    )

    assert [(e.kind, e.at, e.text) for e in events] == [
        (SectionKind.HIGHWAY_OFF, brief_gap.end_time, "State Highway 1を離れ、Tekapoへ"),
        (SectionKind.HIGHWAY_OFF, later.end_time, "State Highway 8を離れる"),
    ]


def test_a_highway_that_runs_to_the_days_end_is_not_left() -> None:
    ride_end = _T0 + timedelta(hours=2)
    run = ScenicStretch("State Highway 1", _T0, ride_end - timedelta(minutes=3))

    assert highway_exits((run,), ride_end=ride_end, language=_JA) == ()


def test_section_timings_are_checked() -> None:
    with pytest.raises(ValueError):
        attach_sections(_plan(_window("a")), (), {"a": _T0}, stays_s=0.0)


def test_the_cold_open_carries_no_line_and_a_line_is_not_repeated() -> None:
    headline = StoryPlanBeat(
        StoryBeatKind.GAP_CARD,
        6.0,
        card=GapChapterCard(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            character=GapCharacter.HEADLINE,
            title="A → B",
            body="b",
            screen_duration_s=6.0,
        ),
    )
    plan = _plan(_window("open"), headline, _window("a"), _window("b"))
    starts = {"open": _T0, "a": _T0 + timedelta(minutes=1), "b": _T0 + timedelta(minutes=20)}
    twice = (
        _event(SectionKind.TOWN, 0.0, "Southbankを通る"),
        _event(SectionKind.TOWN, 19.0, "Southbankを通る"),
    )

    laid = attach_sections(plan, twice, starts)

    assert [b.event_id for b in sections_of(laid)] == ["a"]


def test_a_stop_beside_the_highway_that_rejoins_it_is_no_exit() -> None:
    ride_end = _T0 + timedelta(hours=6)
    before = ScenicStretch("State Highway 1", _T0, _T0 + timedelta(hours=1))
    after = ScenicStretch(
        "State Highway 1", _T0 + timedelta(hours=1, minutes=20), _T0 + timedelta(hours=2)
    )

    def stood(since: datetime, until: datetime) -> float:
        # Three hundred metres between the two runs; a long way after the last.
        return 300.0 if until == after.start_time else 12_000.0

    stood_still = highway_exits((before, after), ride_end=ride_end, language=_JA, advanced=stood)
    rode_away = highway_exits(
        (before, after), ride_end=ride_end, language=_JA, advanced=lambda a, b: 12_000.0
    )

    assert [e.at for e in stood_still] == [after.end_time]
    assert [e.at for e in rode_away] == [before.end_time, after.end_time]


def test_the_day_end_and_highway_lines_and_the_clock() -> None:
    assert departure_line("Northgate", _JA) == "Northgateを出発"
    assert departure_line(None, _EN) == "Setting off"
    assert arrival_line("Ōakfield", _JA) == "Ōakfieldに到着"
    assert arrival_line("Ōakfield", _EN) == "Arriving in Ōakfield"
    assert highway_on_line("State Highway 1", _JA) == "State Highway 1に入る"
    assert with_clock("Northgateを出発", _T0, 13 * 3600.0) == "22:00 · Northgateを出発"
    assert with_clock("Northgateを出発", _T0, None) == "Northgateを出発"


def test_joining_a_highway_is_said_after_being_off_one_not_at_the_days_start() -> None:
    ride_start = _T0
    from_the_start = ScenicStretch(
        "State Highway 1", _T0 + timedelta(minutes=1), _T0 + timedelta(hours=1)
    )
    rejoined_soon = ScenicStretch(
        "State Highway 1", _T0 + timedelta(hours=1, minutes=3), _T0 + timedelta(hours=2)
    )
    after_a_detour = ScenicStretch(
        "State Highway 5", _T0 + timedelta(hours=2, minutes=30), _T0 + timedelta(hours=3)
    )

    events = highway_entries(
        (from_the_start, rejoined_soon, after_a_detour),
        ride_start=ride_start,
        language=_JA,
        advanced=lambda a, b: 12_000.0,
    )

    assert [(e.kind, e.at, e.text) for e in events] == [
        (SectionKind.HIGHWAY_ON, after_a_detour.start_time, "State Highway 5に入る")
    ]
    late_start = ScenicStretch(
        "State Highway 1", _T0 + timedelta(minutes=8), _T0 + timedelta(hours=1)
    )
    assert [e.at for e in highway_entries((late_start,), ride_start=ride_start, language=_JA)] == [
        late_start.start_time
    ]
