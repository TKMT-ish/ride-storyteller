"""Synthetic-fixture tests for the picture of a stop's place, and of the lodging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import VideoAnalysis
from app.gemini_selection import JudgedCandidate
from app.place_shots import (
    lodging_picture,
    picture_of,
    pictures_by_id,
    shows_the_place,
    stop_pictures,
    windows_inside,
)
from app.stop_kinds import StopKind

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _analysis(description: str, *, road: str = "urban street", **fields) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type=road,
        scenery_tags=(),
        weather_visible="clear",
        visual_interest_score=fields.pop("interest", 0.5),
        story_relevance_score=0.5,
        confidence=0.9,
        analysis_provider="gemini",
        **fields,
    )


def _window(name: str, minutes: float, analysis: VideoAnalysis) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=name,
        start_time=_T0 + timedelta(minutes=minutes),
        duration_s=12.0,
        analysis=analysis,
    )


def _stop(minutes: float = 0.0, length_min: float = 20.0) -> tuple[datetime, datetime]:
    return (_T0 + timedelta(minutes=minutes), _T0 + timedelta(minutes=minutes + length_min))


# --- which windows belong to a stop --------------------------------------------


def test_a_window_may_begin_a_little_before_the_track_says_the_ride_stopped() -> None:
    start, end = _stop()
    early = _window("early", -0.4, _analysis("pulling in"))
    outside = _window("outside", -5.0, _analysis("riding"))

    inside = windows_inside((early, outside), start, end)

    assert [c.event_id for c in inside] == ["early"]


def test_a_window_the_model_never_judged_is_not_a_picture_of_anything() -> None:
    start, end = _stop()
    unjudged = JudgedCandidate(
        event_id="none", start_time=_T0 + timedelta(minutes=1), duration_s=12.0, analysis=None
    )

    assert windows_inside((unjudged,), start, end) == ()


# --- what shows the place -------------------------------------------------------


def test_a_standing_frame_a_pulling_in_or_a_named_place_shows_where_the_bike_is() -> None:
    assert shows_the_place(_analysis("riding on", stationary="yes")) is True
    assert shows_the_place(_analysis("riding on", road_event="pulling_in")) is True
    assert shows_the_place(_analysis("a gas station forecourt")) is True
    assert shows_the_place(_analysis("a wide view", highlight_subject="rest_stop")) is True
    assert shows_the_place(_analysis("a plain road ahead", stationary="no")) is False


def test_the_bike_outside_beats_the_exhibit_inside() -> None:
    """The owner's day-2 note (2026-09-07): the museum's own hall was the wrong
    shot; the bike outside it was the right one."""
    hall = _window("hall", 5, _analysis("the interior of a museum hall", stationary="yes"))
    outside = _window(
        "outside", 19, _analysis("the motorcycle parked in the car park", stationary="yes")
    )

    assert picture_of((hall, outside), end=_stop()[1], kind=StopKind.ATTRACTION) == "outside"


def test_a_home_is_never_the_picture_of_a_stop() -> None:
    home = _window("home", 5, _analysis("the driveway of a house", stationary="yes"))

    assert picture_of((home,), end=_stop()[1], kind=StopKind.REST) is None


def test_a_window_the_film_already_keeps_is_not_chosen_again() -> None:
    only = _window("only", 5, _analysis("a gas station forecourt", stationary="yes"))

    assert picture_of((only,), end=_stop()[1], kind=StopKind.FUEL, taken={"only"}) is None


def test_a_frame_the_model_says_has_no_rider_beats_one_it_was_never_asked_about() -> None:
    """The owner's day-5 note (2026-09-07): a stop's picture showed a person
    filling the frame, and the words never said so."""
    unasked = _window("unasked", 5, _analysis("a gas station forecourt", stationary="yes"))
    answered = _window(
        "answered",
        6,
        _analysis("a gas station forecourt", stationary="yes", rider_visible="none"),
    )

    assert picture_of((unasked, answered), end=_stop()[1], kind=StopKind.FUEL) == "answered"


def test_a_ferry_stop_shows_the_boarding() -> None:
    """The owner's day-3 note (2026-09-07): boarding is the event of the day."""
    terminal = _window("terminal", 2, _analysis("the ferry terminal queue", stationary="yes"))
    boarding = _window("boarding", 8, _analysis("the motorcycle riding onto a large ferry"))
    deck = _window("deck", 12, _analysis("the interior vehicle deck of a ferry"))

    assert picture_of((terminal, boarding, deck), end=_stop()[1], kind=StopKind.FERRY) == "boarding"


def test_a_stop_whose_windows_all_look_down_the_road_has_no_picture() -> None:
    ahead = _window("ahead", 5, _analysis("a plain road ahead", stationary="no"))

    assert picture_of((ahead,), end=_stop()[1], kind=StopKind.REST) is None


# --- every stop, with its kind and its name -------------------------------------


def test_each_stop_gets_its_kind_its_name_and_its_picture() -> None:
    judged = (
        _window("fuel", 2, _analysis("a gas station forecourt with a sign for Mill End")),
        _window("road", 40, _analysis("a plain road ahead", stationary="no")),
    )

    pictures = stop_pictures(judged, (_stop(),))

    assert len(pictures) == 1
    assert pictures[0].kind is StopKind.FUEL
    assert pictures[0].spot == "Mill End"
    assert pictures[0].event_id == "fuel"
    assert pictures_by_id(pictures) == {"fuel": pictures[0]}


def test_a_stop_with_nothing_filmed_keeps_its_place_and_says_no_picture() -> None:
    pictures = stop_pictures((), (_stop(),))

    assert pictures[0].event_id is None
    assert pictures[0].kind is StopKind.REST
    assert pictures_by_id(pictures) == {}


def test_the_local_hour_turns_a_meal_into_lunch() -> None:
    judged = (_window("cafe", 2, _analysis("a cafe with a menu board", stationary="yes")),)

    midday = stop_pictures(judged, (_stop(),), local_offset_s=3 * 3600.0)

    assert midday[0].kind is StopKind.LUNCH


# --- the lodging at the day's two ends -------------------------------------------


def test_the_lodging_after_the_arrival_is_the_films_last_picture() -> None:
    """The owner's day-1 note (2026-09-07): the film should end at the hotel
    reception."""
    reception = _window(
        "reception", 3, _analysis("a motel entrance with a reception building", stationary="yes")
    )
    room = _window("room", 5, _analysis("the interior of a hotel room", stationary="yes"))
    road = _window("road", 4, _analysis("a plain road ahead", stationary="no"))

    found = lodging_picture((reception, room, road), at=_T0, after=True)

    assert found == "reception"


def test_the_lodging_before_the_departure_is_found_too() -> None:
    reception = _window(
        "reception", -3, _analysis("a motel entrance with a reception building", stationary="yes")
    )

    assert lodging_picture((reception,), at=_T0, after=False) == "reception"
    assert lodging_picture((reception,), at=_T0, after=True) is None


def test_a_lodging_that_could_be_someones_home_is_refused() -> None:
    drive = _window(
        "drive", 3, _analysis("the driveway of a house beside the motel", stationary="yes")
    )

    assert lodging_picture((drive,), at=_T0, after=True) is None


def test_the_lodging_reach_must_be_positive() -> None:
    with pytest.raises(ValueError):
        lodging_picture((), at=_T0, after=True, within_s=0.0)
