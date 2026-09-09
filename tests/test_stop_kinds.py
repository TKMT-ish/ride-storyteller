"""Synthetic-fixture tests for reading what a stop was, and what a window shows."""

from __future__ import annotations

import pytest

from app.contracts import VideoAnalysis
from app.stop_kinds import (
    PLACE_KIND_VALUES,
    StopKind,
    aboard_a_ferry,
    at_a_ferry,
    at_a_private_residence,
    indoors,
    place_kind_of,
    place_name_of,
    riding_aboard,
    sign_names,
    spot_name,
    stop_kind,
)


def _analysis(description: str, *, road: str = "urban street", **fields) -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type=road,
        scenery_tags=(),
        weather_visible="clear",
        visual_interest_score=0.5,
        story_relevance_score=0.5,
        confidence=0.9,
        analysis_provider="gemini",
        **fields,
    )


# --- what kind of place -------------------------------------------------------


def test_the_models_own_answer_wins_over_its_words() -> None:
    """A judgement bought with the place question answers it outright."""
    said = _analysis("a museum hall full of exhibits", place_kind="fuel")

    assert place_kind_of(said) is StopKind.FUEL


def test_the_words_stand_in_for_a_judgement_bought_before_the_question_existed() -> None:
    assert place_kind_of(_analysis("a gas station forecourt")) is StopKind.FUEL
    assert place_kind_of(_analysis("a museum exhibit of military artifacts")) is StopKind.ATTRACTION
    assert place_kind_of(_analysis("a wooden viewing platform")) is StopKind.LOOKOUT
    assert place_kind_of(_analysis("a cafe with a menu board")) is StopKind.MEAL
    assert place_kind_of(_analysis("a motel entrance and reception")) is StopKind.LODGING
    assert place_kind_of(_analysis("the ferry terminal queue")) is StopKind.FERRY
    assert place_kind_of(_analysis("a plain two-lane road")) is None


def test_an_answer_of_none_is_an_answer_and_stops_the_words_being_read() -> None:
    assert place_kind_of(_analysis("a gas station forecourt", place_kind="none")) is None


def test_an_answer_of_other_is_also_an_answer_not_a_fallback_to_words() -> None:
    assert place_kind_of(_analysis("a gas station forecourt", place_kind="other")) is None


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("fuel", StopKind.FUEL),
        ("eatery", StopKind.MEAL),
        ("lodging", StopKind.LODGING),
        ("attraction", StopKind.ATTRACTION),
        ("lookout", StopKind.LOOKOUT),
        ("shop", StopKind.SHOP),
        ("ferry", StopKind.FERRY),
        ("residential", StopKind.RESIDENCE),
    ],
)
def test_every_bought_answer_maps_to_its_own_kind(answer: str, expected: StopKind) -> None:
    """A plain road with a bought answer takes the answer, not the (silent) words."""
    assert place_kind_of(_analysis("a plain two-lane road", place_kind=answer)) is expected


def test_a_shop_is_read_from_its_words_too() -> None:
    assert place_kind_of(_analysis("a supermarket aisle with groceries")) is StopKind.SHOP
    assert place_kind_of(_analysis("a motorcycle shop with bikes on display")) is StopKind.SHOP


def test_place_kind_values_are_the_contracts_own() -> None:
    assert "fuel" in PLACE_KIND_VALUES and "unknown" in PLACE_KIND_VALUES


# --- what the whole stop was --------------------------------------------------


def test_the_windows_vote_and_the_most_frequent_kind_wins() -> None:
    analyses = (
        _analysis("a gas station forecourt"),
        _analysis("a gas station forecourt"),
        _analysis("a cafe with a menu board"),
    )

    assert stop_kind(analyses, duration_s=600.0) is StopKind.FUEL


def test_a_meal_in_the_middle_of_the_day_is_lunch() -> None:
    """The owner's rule (2026-09-07): lunch and sightseeing are not a fuel stop."""
    analyses = (_analysis("a cafe with a menu board"),)

    assert stop_kind(analyses, duration_s=1800.0, local_hour=12.5) is StopKind.LUNCH
    assert stop_kind(analyses, duration_s=1800.0, local_hour=19.0) is StopKind.MEAL
    assert stop_kind(analyses, duration_s=1800.0) is StopKind.MEAL


def test_the_lunch_hours_are_a_half_open_window() -> None:
    """LUNCH_FROM_H is included, LUNCH_UNTIL_H is not -- a meal right at
    14:30 is dinner-early, not lunch."""
    analyses = (_analysis("a cafe with a menu board"),)

    assert stop_kind(analyses, duration_s=1800.0, local_hour=11.0) is StopKind.LUNCH
    assert stop_kind(analyses, duration_s=1800.0, local_hour=10.99) is StopKind.MEAL
    assert stop_kind(analyses, duration_s=1800.0, local_hour=14.5) is StopKind.MEAL
    assert stop_kind(analyses, duration_s=1800.0, local_hour=14.49) is StopKind.LUNCH


def test_a_ferry_beats_the_cafes_inside_its_terminal() -> None:
    analyses = (
        _analysis("a cafe with a menu board"),
        _analysis("the ferry terminal queue"),
    )

    assert stop_kind(analyses, duration_s=600.0) is StopKind.FERRY


def test_a_stop_the_camera_says_nothing_about_is_read_from_its_length() -> None:
    assert stop_kind((), duration_s=300.0) is StopKind.REST
    assert stop_kind((), duration_s=3600.0) is StopKind.STOPOVER


def test_the_stopover_boundary_belongs_to_the_stopover_side() -> None:
    assert stop_kind((), duration_s=1800.0) is StopKind.STOPOVER
    assert stop_kind((), duration_s=1799.99) is StopKind.REST


def test_a_negative_duration_is_refused() -> None:
    with pytest.raises(ValueError):
        stop_kind((), duration_s=-1.0)


# --- the ferry ----------------------------------------------------------------


def test_a_sign_pointing_at_a_ferry_is_not_a_ferry() -> None:
    """A road sign reading "Ferry Terminal" matched a town's main street; being
    carried needs a deck, a bow, or the vessel's inside."""
    sign = _analysis("a two-lane road in a town, with a sign reading Ferry Terminal")

    assert at_a_ferry(sign) is True
    assert aboard_a_ferry(sign) is False
    assert aboard_a_ferry(_analysis("the interior vehicle deck of a ferry")) is True
    assert aboard_a_ferry(_analysis("the bow of the ferry and open water")) is True


def test_the_boarding_itself_is_recognised() -> None:
    assert riding_aboard(_analysis("the motorcycle riding onto a large ferry")) is True
    assert riding_aboard(_analysis("the interior vehicle deck of a ferry")) is False


def test_the_bought_answer_says_ferry_even_when_the_words_do_not() -> None:
    assert at_a_ferry(_analysis("a plain two-lane road", place_kind="ferry")) is True


# --- indoors, and anyone's home ------------------------------------------------


def test_a_room_is_indoors_and_a_road_is_not() -> None:
    assert indoors(_analysis("the interior of a museum hall")) is True
    assert indoors(_analysis("a two-lane road under a blue sky")) is False


@pytest.mark.parametrize(
    "description",
    [
        "a hallway with paintings on the wall",
        "a kitchenette in the corner of the room",
        "the hotel room with two beds",
        "a lobby with a reception desk",
        "a staircase leading up to the next floor",
        "a lounge area with sofas",
        "a cafeteria with rows of tables",
    ],
)
def test_the_indoors_words_cover_more_than_one_room(description: str) -> None:
    """The pattern names a museum hall, a hotel, and a ferry's inside alike."""
    assert indoors(_analysis(description)) is True


def test_a_home_is_refused_however_it_is_described() -> None:
    """The owner's correction (2026-09-07): a car park is fine; a scene that
    could say whose house this is never is."""
    assert at_a_private_residence(_analysis("rolling down the driveway of a house")) is True
    assert at_a_private_residence(_analysis("an apartment complex car park")) is True
    assert at_a_private_residence(_analysis("a motel car park", place_kind="residential")) is True
    assert at_a_private_residence(_analysis("a supermarket car park")) is False


@pytest.mark.parametrize(
    "description",
    [
        "a carport beside the house",
        "the front yard of a house",
        "the back yard of a house",
        "a single townhouse with a small garden",
        "a garage with the door open",
    ],
)
def test_more_words_that_could_say_whose_home_this_is(description: str) -> None:
    assert at_a_private_residence(_analysis(description)) is True


def test_a_garage_door_seen_shut_is_not_a_garage_scene() -> None:
    """`garage` alone matches, but a closed door on a passing street is not
    a home -- the negative lookahead exists because a real ride's words
    included "garage door" on an ordinary street front."""
    assert at_a_private_residence(_analysis("a garage door closed to the street")) is False


# --- the name on the sign ------------------------------------------------------


def test_a_name_is_read_off_a_sign() -> None:
    found = sign_names("a sign for the Northgate Rail Museum beside the road")

    assert found == ("Northgate Rail Museum",)


def test_a_fragment_that_is_not_a_name_is_not_kept() -> None:
    """The model's quoted fragments included "s a large blue sign for"."""
    assert sign_names("a crossing 's a large blue sign for' ahead") == ()
    assert sign_names("a sign reading STOP at the junction") == ()


def test_a_road_is_not_the_name_of_a_place_to_stop_at() -> None:
    assert sign_names("a sign for the Manawatu Scenic Route") == ()


def test_the_models_own_place_name_wins_over_a_sign() -> None:
    said = _analysis("a sign for the Northgate Rail Museum", place_name="Karāwera Museum")

    assert place_name_of(said) == "Karāwera Museum"
    assert place_name_of(_analysis("a plain road")) is None


def test_an_unanswered_place_name_falls_back_to_the_sign() -> None:
    """ "unknown" and whitespace are not names -- read the sign instead."""
    unknown = _analysis("a sign for the Northgate Rail Museum", place_name="unknown")
    blank = _analysis("a sign for the Northgate Rail Museum", place_name="   ")

    assert place_name_of(unknown) == "Northgate Rail Museum"
    assert place_name_of(blank) == "Northgate Rail Museum"


def test_the_name_most_windows_agree_on_is_the_stops_own() -> None:
    analyses = (
        _analysis("a sign for the Northgate Rail Museum"),
        _analysis("a sign for the Northgate Rail Museum"),
        _analysis("a sign for the Visitor Centre"),
    )

    assert spot_name(analyses) == "Northgate Rail Museum"
    assert spot_name(()) is None


def test_a_tie_in_votes_is_broken_by_the_longer_name() -> None:
    analyses = (
        _analysis("a sign for the Northgate Rail Museum"),
        _analysis("a sign for the Visitor Centre"),
    )

    assert spot_name(analyses) == "Northgate Rail Museum"


def test_a_shouted_three_word_sign_is_a_shop_window_not_a_place() -> None:
    """Real rides produced "TOLLO CHINESE FOOD" and "Wash" off shop fronts."""
    assert sign_names("a sign reading 'TOLLO CHINESE FOOD' above the door") == ()
    # Two shouted words are how a real place signs itself.
    assert sign_names("a sign reading 'STIRLING POINT' at the lookout") == ("STIRLING POINT",)


def test_a_lone_shouted_word_is_a_shop_window_not_a_place() -> None:
    assert sign_names("a sign reading 'WASH' above the door") == ()


def test_a_short_road_code_is_not_a_name() -> None:
    """A route code read off a sign names a road, not a place to stop at."""
    assert sign_names("a sign for the SH1") == ()


def test_a_name_with_more_than_two_digits_is_not_kept() -> None:
    assert sign_names("a sign for the Route 66 2024 Rally") == ()


def test_a_name_of_more_than_five_words_is_not_kept() -> None:
    assert sign_names("a sign for the Northgate Rail Museum Visitor Information Centre") == ()


@pytest.mark.parametrize(
    "phrasing",
    [
        "a sign reading the Northgate Rail Museum",
        "a sign that reads the Northgate Rail Museum",
        "a sign saying the Northgate Rail Museum",
        "a sign says the Northgate Rail Museum",
        "a sign indicating the Northgate Rail Museum",
        "signage for the Northgate Rail Museum",
    ],
)
def test_every_way_the_model_introduces_a_sign_is_read(phrasing: str) -> None:
    assert sign_names(phrasing) == ("Northgate Rail Museum",)


def test_the_same_name_found_twice_is_kept_once() -> None:
    found = sign_names("a sign for the Northgate Rail Museum, 'Northgate Rail Museum' ahead")

    assert found == ("Northgate Rail Museum",)
