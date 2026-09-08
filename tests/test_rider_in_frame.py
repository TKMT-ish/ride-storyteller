"""Synthetic-fixture tests for keeping the rider out of the picture."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.contracts import VideoAnalysis
from app.rider_in_frame import (
    describes_the_rider,
    parked_in_a_car_park,
    rider_fills_the_frame,
)


def _analysis(description: str, *, rider_visible: str = "unknown") -> VideoAnalysis:
    return VideoAnalysis(
        asset_id="asset-synthetic-1",
        start_offset_s=0.0,
        end_offset_s=12.0,
        visual_description=description,
        road_type="rural highway",
        scenery_tags=("trees",),
        weather_visible="clear",
        visual_interest_score=0.8,
        story_relevance_score=0.8,
        confidence=0.9,
        analysis_provider="gemini",
        rider_visible=rider_visible,
    )


@pytest.mark.parametrize(
    "description",
    [
        "A static view from a parked motorcycle, the rearview mirror reflecting the rider.",
        "A scenic view from a parked vehicle, with a person's arm visible in the foreground.",
        "The video shows a person in full motorcycle gear, including a helmet with a chin bar.",
        "The rider's reflection is clearly visible in the mirror while stopped at a station.",
        "A man standing next to the motorcycle looks at the view.",
    ],
)
def test_the_models_words_for_the_rider_are_recognised(description: str) -> None:
    assert describes_the_rider(description)


@pytest.mark.parametrize(
    "description",
    [
        "The video shows a first-person view from a motorcycle on a two-lane road.",
        "Farmland stretches along the right-hand side of the road under a clear sky.",
        "A person is seen getting into the passenger side of a white car in a car park.",
        "People walking along the footpath in a small town as the motorcycle passes.",
        "A helmet-mounted camera view of a winding road climbing through forest.",
        "The view from a camera mounted on the helmet shows the road ahead.",
    ],
)
def test_the_road_the_camera_and_passers_by_are_not_the_rider(description: str) -> None:
    assert not describes_the_rider(description)


def test_the_models_own_answer_wins_over_its_words() -> None:
    """Once the model is asked, its answer is the evidence, not a phrase."""
    words_only = _analysis("the mirror reflecting the rider")

    assert rider_fills_the_frame(words_only)
    # "small" is the model's word; where its words describe the rider in the
    # mirror, the words win (the owner saw the rider large on day 1).
    assert rider_fills_the_frame(replace(words_only, rider_visible="small"))
    assert not rider_fills_the_frame(replace(words_only, rider_visible="none"))
    assert not rider_fills_the_frame(_analysis("A road through trees", rider_visible="small"))
    assert rider_fills_the_frame(_analysis("A road through trees", rider_visible="large"))


def test_an_answer_the_model_never_gave_is_refused() -> None:
    with pytest.raises(ValueError):
        _analysis("A road", rider_visible="maybe")


@pytest.mark.parametrize(
    "phrase",
    [
        "car park",
        "carpark",
        "CAR PARK",
        "parking lot",
        "parking area",
        "parking garage",
        "parking space",
        "parking bay",
        "forecourt",
        "driveway",
        "parking-lot",
    ],
)
def test_the_owners_words_for_a_car_park_are_recognised(phrase: str) -> None:
    """Every phrase the owner's rule (point 9) names for a parked-vehicle place."""
    assert parked_in_a_car_park(_analysis(f"A view across the {phrase}."))


@pytest.mark.parametrize(
    "description",
    [
        "The motorcycle is parked on the side of the road.",
        "A scenic view of a national park in the distance.",
        "The amusement park's rides are visible over the trees.",
        "A rural highway winds through farmland.",
        "parkinglot",
    ],
)
def test_being_parked_or_a_park_by_name_is_not_a_car_park(description: str) -> None:
    """Being parked, a national park, and a run-together "parkinglot" don't count."""
    assert not parked_in_a_car_park(_analysis(description))


def test_the_road_type_field_is_searched_as_well_as_the_description() -> None:
    """The model can say "car park" in either field; the caller reads both."""
    analysis = replace(_analysis("A view of the mountains."), road_type="car park")

    assert parked_in_a_car_park(analysis)
