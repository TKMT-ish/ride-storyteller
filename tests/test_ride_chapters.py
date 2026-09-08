"""Synthetic-track tests for cutting a day into chapters and naming them.

The track is invented and says nothing about any place. What is held is
where the day is cut -- at a long halt, at a silence in the track, at a
pass with climbing on both sides -- how many chapters come out, that no
title is used twice, that the body states only what the track proves,
and that the timeline puts each chapter's card before its windows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.agents import StoryOutputLanguage
from app.contracts import RoutePoint
from app.gap_chapters import GapCharacter
from app.ride_chapters import (
    CHAPTER_CARD_S,
    LONG_LEG_S,
    MAX_CHAPTERS,
    TARGET_CHAPTERS,
    RideChapter,
    RideChapterError,
    build_chapter_timeline,
    chapter_cards,
    day_account,
    describe_chapter,
    long_halts,
    passes,
    segment_ride,
)
from app.story_package import JourneyStoryPlanError, build_journey_story_plan
from app.story_timeline import StoryBeatKind, TimelineFootage

_T0 = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)
_STEP_S = 10.0


def _track(
    *,
    hours: float,
    height_at: object = lambda second: 100.0,
    halt: tuple[float, float] | None = None,
    silence: tuple[float, float] | None = None,
) -> tuple[RoutePoint, ...]:
    """A ride at 20 m/s, with a chosen profile, an optional halt and silence."""
    points: list[RoutePoint] = []
    distance = 0.0
    second = 0.0
    while second <= hours * 3600.0:
        if silence and silence[0] < second < silence[1]:
            second += _STEP_S
            continue
        moving = not (halt and halt[0] <= second <= halt[1])
        speed = 20.0 if moving else 0.0
        if points:
            distance += speed * _STEP_S
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 + distance / 111_000.0,
                longitude=170.0,
                elevation_m=float(height_at(second)),
                distance_from_start_m=distance,
                speed_mps=speed if points else None,
            )
        )
        second += _STEP_S
    return tuple(points)


def _mountain(second: float) -> float:
    """Up to a pass at two hours, down again by four."""
    peak = 2 * 3600.0
    return 100.0 + max(0.0, 900.0 - abs(second - peak) / 8.0)


# --- where the day is cut ----------------------------------------------------------


def test_a_flat_day_without_a_stop_is_cut_into_about_five_parts() -> None:
    """Four hours with no halt: five even legs, departure first, arrival last (point 7)."""
    chapters = segment_ride(_track(hours=4))

    assert len(chapters) == TARGET_CHAPTERS
    assert chapters[0].character is GapCharacter.DEPARTURE
    assert chapters[-1].character is GapCharacter.ARRIVAL
    assert chapters[0].since_departure_s == 0.0
    assert all(c.duration_s <= LONG_LEG_S + 1.0 for c in chapters)
    assert all(c.halt_s == 0.0 for c in chapters)


def test_a_day_with_many_stops_is_not_cut_further_for_the_target() -> None:
    """Two halts and a target of two: the halts alone shape the day."""
    track = _track(hours=4)

    assert [c.character for c in segment_ride(track, target_chapters=2)] == [
        GapCharacter.DEPARTURE,
        GapCharacter.ARRIVAL,
    ]


def test_a_pass_is_found_only_with_climbing_on_both_sides() -> None:
    assert passes(_track(hours=4)) == []
    found = passes(_track(hours=4, height_at=_mountain))
    assert len(found) == 1
    assert abs((found[0] - (_T0 + timedelta(hours=2))).total_seconds()) < 120


def test_a_long_leg_is_cut_at_the_pass_and_the_leg_that_climbs_to_it_is_named_for_it() -> None:
    chapters = segment_ride(_track(hours=4, height_at=_mountain))

    characters = [chapter.character for chapter in chapters]
    assert GapCharacter.PASS in characters
    over = characters.index(GapCharacter.PASS)
    assert chapters[over].elevation_gain_m > chapters[over].elevation_loss_m
    assert all(c is not GapCharacter.PASS for c in characters[over + 1 :])
    # The cut is the pass itself, not the middle of the day by the clock.
    assert abs((chapters[over].end_time - (_T0 + timedelta(hours=2))).total_seconds()) < 120


def test_a_long_halt_ends_a_leg_which_says_how_long_the_ride_stood() -> None:
    """The owner's frame: chapters are legs, halt to halt; the halt is the leg's end."""
    track = _track(hours=5, halt=(2 * 3600.0, 2 * 3600.0 + 25 * 60.0))

    assert len(long_halts(track)) == 1
    chapters = segment_ride(track)
    assert all(chapter.character is not GapCharacter.HALT for chapter in chapters)
    stood = [chapter for chapter in chapters if chapter.halt_s > 0]
    assert len(stood) == 1
    assert 24 * 60 <= stood[0].halt_s <= 26 * 60
    # The leg ends where the riding starts again, and the next begins there.
    after = chapters[chapters.index(stood[0]) + 1]
    assert after.start_time == stood[0].end_time
    assert after.halt_s == 0.0


def test_a_silence_in_the_track_is_a_halt_too() -> None:
    """Indoors the GPS says nothing at all; that is still one place."""
    track = _track(hours=5, silence=(3 * 3600.0, 3 * 3600.0 + 40 * 60.0))

    halts = long_halts(track)
    assert len(halts) == 1
    assert 39 * 60 <= (halts[0][1] - halts[0][0]).total_seconds() <= 41 * 60
    assert any(39 * 60 <= c.halt_s <= 41 * 60 for c in segment_ride(track))


def test_no_leg_runs_longer_than_a_long_leg_and_the_count_is_capped() -> None:
    chapters = segment_ride(_track(hours=9))

    assert max(c.duration_s for c in chapters) <= LONG_LEG_S + 1.0
    assert len(chapters) <= MAX_CHAPTERS


def test_too_many_halts_fold_the_shortest_legs_into_their_neighbours() -> None:
    """Seven stops make eight legs; the film has room for six chapters."""
    track = _track(hours=9)
    chapters = segment_ride(track, maximum_chapters=3, long_leg_s=3600.0, target_chapters=3)

    assert len(chapters) == 3
    assert chapters[0].start_time == track[0].timestamp
    assert chapters[-1].end_time == track[-1].timestamp
    assert all(a.end_time == b.start_time for a, b in zip(chapters, chapters[1:], strict=False))


def test_the_models_words_choose_between_titles_the_track_allows() -> None:
    track = _track(hours=4)
    hints = {_T0 + timedelta(hours=1, minutes=30): "winding coastal road sea spray"}

    chapters = segment_ride(track, hints=hints)
    inside = [
        c for c in chapters if c.start_time <= _T0 + timedelta(hours=1, minutes=30) < c.end_time
    ]
    assert inside[0].character is GapCharacter.COAST


def test_a_ride_needs_two_points_and_sane_bounds() -> None:
    track = _track(hours=1)
    with pytest.raises(RideChapterError, match="two track points"):
        segment_ride(track[:1])
    with pytest.raises(RideChapterError, match="nonsense"):
        segment_ride(track, minimum_chapters=3, maximum_chapters=2)


# --- naming -----------------------------------------------------------------------


def test_no_title_is_used_twice_in_one_film() -> None:
    chapters = segment_ride(_track(hours=9))
    for language in StoryOutputLanguage:
        titles = [card.title for card in chapter_cards(chapters, output_language=language)]
        assert len(titles) == len(set(titles))


def test_the_body_states_time_since_departure_and_distance() -> None:
    cards = chapter_cards(segment_ride(_track(hours=4)))

    assert cards[0].body.startswith("出発 · ")
    assert "出発から" in cards[1].body
    assert "km" in cards[1].body
    assert all(card.screen_duration_s == CHAPTER_CARD_S for card in cards)


def test_a_halt_card_says_how_long_the_ride_stayed() -> None:
    track = _track(hours=5, halt=(2 * 3600.0, 2 * 3600.0 + 25 * 60.0))
    cards = chapter_cards(segment_ride(track))

    stood = [card for card in cards if "ここで" in card.body]
    assert len(stood) == 1
    assert "ここで25分" in stood[0].body or "ここで24分" in stood[0].body
    # The leg still says how far it rode before the stop.
    assert "km" in stood[0].body


def test_cards_carry_their_place_on_the_rides_clock() -> None:
    chapters = segment_ride(_track(hours=4))
    cards = chapter_cards(chapters)

    assert all(card.is_on_the_clock for card in cards)
    assert [card.since_departure_s for card in cards] == [c.since_departure_s for c in chapters]
    assert [card.duration_s for card in cards] == [c.duration_s for c in chapters]


def test_cards_carry_no_coordinate_timestamp_or_identifier() -> None:
    written = json.dumps(
        [card.to_dict() for card in chapter_cards(segment_ride(_track(hours=4)))],
        ensure_ascii=False,
    )
    assert "-43." not in written and "170." not in written
    assert "2026-05-01" not in written and "T06:" not in written


# --- the timeline -------------------------------------------------------------------


def _clip(name: str, at: timedelta) -> TimelineFootage:
    return TimelineFootage(
        event_id=name, start_time=_T0 + at, end_time=_T0 + at + timedelta(seconds=12)
    )


def test_each_chapter_opens_with_its_card_and_shows_its_windows_in_order() -> None:
    track = _track(hours=4)
    chapters = segment_ride(track)
    clips = (
        _clip("late", timedelta(hours=3, minutes=10)),
        _clip("early", timedelta(minutes=20)),
        _clip("middle", timedelta(hours=1, minutes=40)),
    )

    timeline = build_chapter_timeline(chapters, clips, track)

    kinds = [beat.kind for beat in timeline.beats]
    assert kinds.count(StoryBeatKind.GAP_CARD) == len(chapters)
    assert kinds[0] is StoryBeatKind.GAP_CARD
    assert [b.event_id for b in timeline.beats if b.event_id] == ["early", "middle", "late"]
    # Every window follows the card of the chapter it lies in.
    for index, beat in enumerate(timeline.beats):
        if beat.kind is StoryBeatKind.FOOTAGE:
            card = next(
                b for b in reversed(timeline.beats[:index]) if b.kind is StoryBeatKind.GAP_CARD
            )
            assert card.ride_start_time <= beat.ride_start_time


def test_a_chapter_without_a_window_keeps_its_card() -> None:
    track = _track(hours=4)
    chapters = segment_ride(track)
    timeline = build_chapter_timeline(chapters, (_clip("only", timedelta(minutes=20)),), track)

    assert len(timeline.gap_beats) == len(chapters)
    assert len(timeline.footage_beats) == 1


def test_the_plan_takes_the_chapter_cards_and_refuses_a_mismatch() -> None:
    track = _track(hours=4)
    chapters = segment_ride(track)
    timeline = build_chapter_timeline(chapters, (_clip("only", timedelta(minutes=20)),), track)
    cards = chapter_cards(chapters)

    plan = build_journey_story_plan(timeline, cards=cards)
    assert [beat.card.title for beat in plan.card_beats] == [card.title for card in cards]

    with pytest.raises(JourneyStoryPlanError, match="one card per card beat"):
        build_journey_story_plan(timeline, cards=cards[:-1])


# --- RideChapter's own guards -------------------------------------------------------


def _chapter(
    character: GapCharacter,
    *,
    start: datetime = _T0,
    duration_s: float = 15 * 60.0,
    distance_m: float = 1_000.0,
    gain_m: float = 0.0,
    loss_m: float = 0.0,
    first_m: float | None = None,
    last_m: float | None = None,
) -> RideChapter:
    return RideChapter(
        start_time=start,
        end_time=start + timedelta(seconds=duration_s),
        character=character,
        distance_m=distance_m,
        elevation_gain_m=gain_m,
        elevation_loss_m=loss_m,
        start_elevation_m=first_m,
        end_elevation_m=last_m,
        since_departure_s=(start - _T0).total_seconds(),
    )


def test_a_chapter_rejects_a_span_that_does_not_run_forward() -> None:
    with pytest.raises(ValueError, match="positive duration"):
        RideChapter(
            start_time=_T0,
            end_time=_T0,
            character=GapCharacter.LINK,
            distance_m=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            start_elevation_m=None,
            end_elevation_m=None,
            since_departure_s=0.0,
        )


@pytest.mark.parametrize("field", ["distance_m", "gain_m", "loss_m"])
def test_a_chapter_rejects_a_negative_aggregate(field: str) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        _chapter(GapCharacter.LINK, **{field: -1.0})


def test_a_chapters_to_dict_carries_only_its_aggregates() -> None:
    chapter = _chapter(GapCharacter.CLIMB, start=_T0 + timedelta(hours=1), gain_m=250.0)

    written = json.dumps(chapter.to_dict(), ensure_ascii=False)
    assert "2026-05-01" not in written and "06:00" not in written
    assert set(chapter.to_dict()) == {
        "character",
        "duration_s",
        "distance_m",
        "elevation_gain_m",
        "elevation_loss_m",
        "since_departure_s",
        "halt_s",
        "route_name",
    }


# --- describing a chapter's body -----------------------------------------------------


def test_describe_chapter_states_the_elevation_span_when_it_is_worth_stating() -> None:
    chapter = _chapter(GapCharacter.CLIMB, first_m=100.0, last_m=250.0)
    assert "海抜100m → 250m" in describe_chapter(chapter, StoryOutputLanguage.JAPANESE)
    assert "100 m → 250 m" in describe_chapter(chapter, StoryOutputLanguage.ENGLISH)


def test_describe_chapter_falls_back_to_gain_and_loss_without_endpoints() -> None:
    chapter = _chapter(GapCharacter.WINDING, gain_m=120.0, loss_m=30.0)
    assert "登り120m / 下り30m" in describe_chapter(chapter, StoryOutputLanguage.JAPANESE)
    assert "+120 m / -30 m" in describe_chapter(chapter, StoryOutputLanguage.ENGLISH)


def test_describe_chapter_says_nothing_of_elevation_when_it_barely_changed() -> None:
    chapter = _chapter(GapCharacter.LINK, first_m=100.0, last_m=140.0, gain_m=40.0, loss_m=10.0)
    body = describe_chapter(chapter, StoryOutputLanguage.JAPANESE)
    assert "海抜" not in body and "登り" not in body


def test_describe_chapter_switches_to_kilometres_at_one_thousand_metres() -> None:
    just_under = _chapter(GapCharacter.LINK, distance_m=999.0)
    exactly = _chapter(GapCharacter.LINK, distance_m=1_000.0)
    assert "999m" in describe_chapter(just_under, StoryOutputLanguage.JAPANESE)
    assert "1.0km" in describe_chapter(exactly, StoryOutputLanguage.JAPANESE)


def test_describe_chapter_carries_the_hour_across_the_sixty_minute_mark() -> None:
    at_the_mark = _chapter(GapCharacter.LINK, start=_T0 + timedelta(hours=1))
    just_before = _chapter(GapCharacter.LINK, start=_T0 + timedelta(hours=1) - timedelta(seconds=1))
    assert "出発から1時間00分" in describe_chapter(at_the_mark, StoryOutputLanguage.JAPANESE)
    assert "出発から59分" in describe_chapter(just_before, StoryOutputLanguage.JAPANESE)


# --- naming past the point where a character has anything new to say ----------------


def test_a_run_of_passes_falls_back_to_the_shared_spare_titles_without_repeating() -> None:
    chapters = tuple(
        _chapter(GapCharacter.PASS, start=_T0 + timedelta(hours=index)) for index in range(7)
    )

    titles = [card.title for card in chapter_cards(chapters)]

    assert len(titles) == len(set(titles))
    # The three PASS titles, then the three LINK spares, then a numbered spare.
    assert titles[:3] == ["峠を越える", "稜線へ", "次の峠"]
    assert titles[3:6] == ["先へ", "道が変わる", "その先"]
    assert titles[6] == "その先 4"


# --- day_account: the whole day's own aggregates -------------------------------------


def test_day_account_reports_the_whole_days_distance_duration_and_relief() -> None:
    track = _track(hours=4, height_at=_mountain)

    distance, duration, gain, loss = day_account(track)

    assert distance == pytest.approx(track[-1].distance_from_start_m)
    assert duration == pytest.approx(4 * 3600.0)
    assert gain > 0.0 and loss > 0.0
    assert gain == pytest.approx(loss, rel=0.05)


def test_day_account_needs_two_track_points() -> None:
    track = _track(hours=1)
    with pytest.raises(RideChapterError, match="two track points"):
        day_account(track[:1])


# --- build_chapter_timeline's own guards ---------------------------------------------


def test_a_timeline_needs_at_least_one_chapter() -> None:
    with pytest.raises(RideChapterError, match="at least one chapter"):
        build_chapter_timeline((), (), _track(hours=1))


def test_two_windows_crowding_a_chapter_boundary_refuse_to_build_a_timeline() -> None:
    chapter_a = _chapter(GapCharacter.LINK, start=_T0, duration_s=10 * 60.0)
    chapter_b = _chapter(GapCharacter.LINK, start=_T0 + timedelta(minutes=10), duration_s=10 * 60.0)
    # The first chapter's window ends half a second before the boundary; the
    # second chapter's window starts exactly on it, leaving less than the
    # second a card needs once the boundary backs its start up.
    boundary = _T0 + timedelta(minutes=10)
    clip_in_a = TimelineFootage(
        event_id="a",
        start_time=boundary - timedelta(seconds=5.5),
        end_time=boundary - timedelta(seconds=0.5),
    )
    clip_in_b = TimelineFootage(
        event_id="b", start_time=boundary, end_time=boundary + timedelta(seconds=5)
    )

    with pytest.raises(RideChapterError, match="two windows leave no room"):
        build_chapter_timeline((chapter_a, chapter_b), (clip_in_a, clip_in_b), _track(hours=1))


# --- the small readers underneath long_halts and passes -------------------------------


def test_long_halts_needs_at_least_two_points() -> None:
    track = _track(hours=1)
    assert long_halts(track[:1]) == []
    assert long_halts(()) == []


def test_passes_needs_at_least_three_elevated_points() -> None:
    track = _track(hours=1, height_at=_mountain)
    assert passes(track[:2]) == []


# --- where each leg went from and to -----------------------------------------


def test_with_names_the_title_is_the_two_places_and_the_phrase_moves_into_the_body() -> None:
    from app.place_names import PlaceName

    chapters = segment_ride(_track(hours=4), target_chapters=2)
    names = [
        (PlaceName("Ashton", None), PlaceName("Marbury", None)),
        (PlaceName("Marbury", None), PlaceName("Karāwera", None)),
    ]

    cards = chapter_cards(chapters, names=names)

    assert cards[0].title == "Ashton → Marbury"
    assert cards[0].body.startswith("出発 · ") and "出発 · 出発" not in cards[0].body
    assert cards[1].title == "Marbury → Karāwera"
    assert cards[1].body.startswith("到着へ · 出発から")


def test_a_leg_with_one_end_named_says_from_or_to_and_an_unnamed_leg_keeps_its_phrase() -> None:
    from app.place_names import NOTHING, PlaceName

    chapters = segment_ride(_track(hours=4), target_chapters=2)
    names = [(PlaceName("Ashton", None), NOTHING), (NOTHING, NOTHING)]

    cards = chapter_cards(chapters, names=names)

    assert cards[0].title == "Ashtonから"
    assert cards[1].title == "到着へ"
    assert not cards[1].body.startswith("到着へ")

    english = chapter_cards(chapters, output_language=StoryOutputLanguage.ENGLISH, names=names)
    assert english[0].title == "From Ashton"


def test_a_leg_that_stayed_in_one_place_is_titled_with_that_place() -> None:
    from app.place_names import PlaceName

    chapters = segment_ride(_track(hours=4), target_chapters=2)
    same = [(PlaceName("Queenstown", None), PlaceName("Queenstown", None))] * 2

    assert chapter_cards(chapters, names=same)[0].title == "Queenstown"


# --- a scenic route is one chapter -------------------------------------------


def test_a_scenic_stretch_is_its_own_chapter_named_for_the_route() -> None:
    from app.scenic_routes import ScenicStretch

    track = _track(hours=6)
    stretch = ScenicStretch(
        "Southern Scenic Route", _T0 + timedelta(hours=1), _T0 + timedelta(hours=4)
    )

    chapters = segment_ride(track, scenic=(stretch,))

    named = [c for c in chapters if c.route_name]
    assert len(named) == 1
    assert named[0].start_time == stretch.start_time
    assert named[0].end_time == stretch.end_time
    # Three hours on the route stay one chapter; the rest is cut as before.
    assert named[0].duration_s == 3 * 3600.0
    assert all(c.duration_s <= LONG_LEG_S + 1.0 for c in chapters if not c.route_name)
    cards = chapter_cards(chapters)
    assert cards[chapters.index(named[0])].title == "Southern Scenic Route"


def test_a_scenic_end_near_a_halt_takes_the_halts_cut() -> None:
    from app.scenic_routes import ScenicStretch

    halt = (2 * 3600.0, 2 * 3600.0 + 25 * 60.0)
    track = _track(hours=5, halt=halt)
    ends_near_the_halt = ScenicStretch(
        "R", _T0 + timedelta(minutes=30), _T0 + timedelta(hours=2, minutes=35)
    )

    chapters = segment_ride(track, scenic=(ends_near_the_halt,))

    scenic = [c for c in chapters if c.route_name][0]
    assert scenic.halt_s > 0  # it ends exactly where the halt does
    assert all(c.duration_s >= 60.0 for c in chapters)


def _two_stop_track(hours: float, stops: tuple[tuple[float, float], ...]) -> tuple[RoutePoint, ...]:
    """A ride at 20 m/s that stands still through each (start_s, end_s) stop."""
    points: list[RoutePoint] = []
    distance = 0.0
    second = 0.0
    while second <= hours * 3600.0:
        moving = not any(a <= second <= b for a, b in stops)
        if points and moving:
            distance += 20.0 * _STEP_S
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 + distance / 111_000.0,
                longitude=170.0,
                elevation_m=100.0,
                distance_from_start_m=distance,
                speed_mps=20.0 if moving else 0.0,
            )
        )
        second += _STEP_S
    return tuple(points)


def test_a_day_with_one_long_halt_promotes_its_short_stops_to_cuts() -> None:
    """The owner (2026-09-07): day 1's fuel stops become small cuts because the day has few."""
    long_stop = (3 * 3600.0, 3 * 3600.0 + 20 * 60.0)
    short_stop = (4 * 3600.0 + 20 * 60.0, 4 * 3600.0 + 27 * 60.0)
    track = _two_stop_track(6, (long_stop, short_stop))

    assert len(long_halts(track)) == 1
    chapters = segment_ride(track)

    assert len(chapters) == 3
    assert sorted(int(c.halt_s // 60) for c in chapters) == [0, 7, 20]
    # A day that already has enough cuts keeps its short stops as sections.
    assert [int(c.halt_s // 60) for c in segment_ride(track, minimum_legs=1)] == [20, 0]
