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


def test_a_ferry_beats_the_cafes_inside_its_terminal() -> None:
    analyses = (
        _analysis("a cafe with a menu board"),
        _analysis("the ferry terminal queue"),
    )

    assert stop_kind(analyses, duration_s=600.0) is StopKind.FERRY


def test_a_stop_the_camera_says_nothing_about_is_read_from_its_length() -> None:
    assert stop_kind((), duration_s=300.0) is StopKind.REST
    assert stop_kind((), duration_s=3600.0) is StopKind.STOPOVER


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


# --- indoors, and anyone's home ------------------------------------------------


def test_a_room_is_indoors_and_a_road_is_not() -> None:
    assert indoors(_analysis("the interior of a museum hall")) is True
    assert indoors(_analysis("a two-lane road under a blue sky")) is False


def test_a_home_is_refused_however_it_is_described() -> None:
    """The owner's correction (2026-09-07): a car park is fine; a scene that
    could say whose house this is never is."""
    assert at_a_private_residence(_analysis("rolling down the driveway of a house")) is True
    assert at_a_private_residence(_analysis("an apartment complex car park")) is True
    assert at_a_private_residence(_analysis("a motel car park", place_kind="residential")) is True
    assert at_a_private_residence(_analysis("a supermarket car park")) is False


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


def test_the_name_most_windows_agree_on_is_the_stops_own() -> None:
    analyses = (
        _analysis("a sign for the Northgate Rail Museum"),
        _analysis("a sign for the Northgate Rail Museum"),
        _analysis("a sign for the Visitor Centre"),
    )

    assert spot_name(analyses) == "Northgate Rail Museum"
    assert spot_name(()) is None


def test_a_shouted_three_word_sign_is_a_shop_window_not_a_place() -> None:
    """Real rides produced "TOLLO CHINESE FOOD" and "Wash" off shop fronts."""
    assert sign_names("a sign reading 'TOLLO CHINESE FOOD' above the door") == ()
    # Two shouted words are how a real place signs itself.
    assert sign_names("a sign reading 'STIRLING POINT' at the lookout") == ("STIRLING POINT",)
