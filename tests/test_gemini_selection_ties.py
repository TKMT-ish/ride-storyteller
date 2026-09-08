"""Synthetic-fixture tests for what selection does when the model did not decide.

On the first real ride the model scored a third of the windows exactly
alike, twice over. Best-first then has to say which of the alike ones
speaks for a stretch, and these hold that it picks by what the film has not
shown yet rather than by whichever the camera saw first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import VideoAnalysis
from app.gemini_selection import (
    DEFAULT_TIE_EPSILON,
    REASON_SAME_HALT,
    REASON_SELECTED,
    GeminiSelectionError,
    JudgedCandidate,
    road_family,
    select_judged_candidates,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _judged(
    event_id: str,
    *,
    at_s: float,
    road: str,
    interest: float = 0.6,
    story: float = 0.7,
    halt: int | None = None,
) -> JudgedCandidate:
    return JudgedCandidate(
        event_id=event_id,
        start_time=_T0 + timedelta(seconds=at_s),
        duration_s=12.0,
        halt=halt,
        analysis=VideoAnalysis(
            asset_id="asset-1",
            start_offset_s=at_s,
            end_offset_s=at_s + 12.0,
            visual_description="a road",
            road_type=road,
            scenery_tags=("sky",),
            weather_visible="clear",
            visual_interest_score=interest,
            story_relevance_score=story,
            confidence=0.9,
            analysis_provider="gemini",
        ),
    )


def _chosen(candidates, **kwargs) -> list[str]:
    return list(select_judged_candidates(candidates, **kwargs).selected_event_ids)


# --- the model's ranking is untouched -----------------------------------------


def test_a_clearly_better_window_is_still_taken_first() -> None:
    """Variety only breaks ties; it never outranks a real difference."""
    candidates = (
        _judged("dull-a", at_s=0, road="highway", interest=0.5, story=0.5),
        _judged("dull-b", at_s=600, road="highway", interest=0.5, story=0.5),
        _judged("great", at_s=1200, road="highway", interest=0.9, story=0.9),
    )

    taken = _chosen(candidates, footage_target_s=12.0)

    assert taken == ["great"]


def test_windows_within_the_margin_count_as_tied_and_beyond_it_do_not() -> None:
    a = _judged("a", at_s=0, road="highway", interest=0.60, story=0.70)
    b = _judged("b", at_s=600, road="street", interest=0.60, story=0.69)
    c = _judged("c", at_s=1200, road="street", interest=0.50, story=0.50)
    #  a and b differ by 0.006, well inside the margin: b's different road wins
    #  the first pick only once a highway is already taken; with nothing
    #  taken, both are novel, and the tie falls to the earliest.
    assert _chosen((a, b, c), footage_target_s=12.0) == ["a"]
    #  c is far below the margin and must not be preferred for its variety.
    assert _chosen((a, c), footage_target_s=12.0) == ["a"]


# --- among alike windows, show a kind of road not yet shown ------------------


def test_among_tied_windows_the_unseen_kind_of_road_is_taken_next() -> None:
    """Ten of twenty clips said "highway" outright on the real ride."""
    candidates = (
        _judged("hw-1", at_s=0, road="highway"),
        _judged("hw-2", at_s=600, road="Asphalt highway"),
        _judged("hw-3", at_s=1200, road="Multi-lane highway"),
        _judged("rural", at_s=1800, road="Asphalt, two-lane, rural road"),
        _judged("hw-4", at_s=2400, road="highway"),
    )

    taken = _chosen(candidates, footage_target_s=24.0)

    assert taken[0] == "hw-1"
    assert "rural" in taken, "a tied window of a different kind was passed over"
    assert len(taken) == 2


def test_the_film_ends_up_with_more_kinds_of_road_than_ride_order_would_give() -> None:
    roads = ["highway"] * 6 + ["suburban street", "parking lot", "roundabout"]
    candidates = tuple(_judged(f"w{i}", at_s=i * 600, road=road) for i, road in enumerate(roads))

    taken = _chosen(candidates, footage_target_s=48.0)
    families = {road_family(c.analysis.road_type) for c in candidates if c.event_id in taken}

    # Every kind of road gets a turn before any is shown twice. A car park
    # is one of them again: the owner's ninth rule (2026-09-06) was
    # corrected on 2026-09-07 to keep out only what could identify a home.
    assert len(taken) == 4
    assert families == {"highway", "street", "junction", "parking"}


def test_once_every_kind_is_shown_the_least_repeated_is_taken_again() -> None:
    candidates = (
        _judged("hw-1", at_s=0, road="highway"),
        _judged("st-1", at_s=600, road="street"),
        _judged("hw-2", at_s=1200, road="highway"),
        _judged("hw-3", at_s=1800, road="highway"),
        _judged("st-2", at_s=2400, road="street"),
    )

    taken = _chosen(candidates, footage_target_s=48.0)

    families = [road_family(c.analysis.road_type) for c in candidates if c.event_id in taken]
    assert families.count("highway") == 2
    assert families.count("street") == 2


# --- failing that, the window farthest from what is already taken -------------


def test_among_tied_windows_of_one_kind_the_farthest_from_the_taken_is_next() -> None:
    """Ride order fills the first half of the journey and none of the second."""
    candidates = tuple(_judged(f"w{i}", at_s=i * 300, road="highway") for i in range(10))

    taken = _chosen(candidates, footage_target_s=36.0)
    positions = sorted(int(e[1:]) for e in taken)

    assert positions[0] == 0
    assert positions[-1] == 9, "the end of the ride was never reached"
    assert len(positions) == 3


# --- the road label is read coarsely, and only for this --------------------


@pytest.mark.parametrize(
    ("label", "family"),
    [
        ("highway", "highway"),
        ("Asphalt highway", "highway"),
        ("Multi-lane arterial road", "highway"),
        ("Paved two-lane highway/main road", "highway"),
        ("Asphalt, two-lane, rural road", "rural"),
        ("mountain road", "rural"),
        ("Suburban street", "street"),
        ("Asphalt road, suburban street, roundabout", "junction"),
        ("Intersection", "junction"),
        ("Parking lot", "parking"),
        ("  Paved   road  ", "paved road"),
        ("", "unknown"),
    ],
)
def test_road_labels_fall_into_a_few_families(label: str, family: str) -> None:
    assert road_family(label) == family


def test_the_family_never_changes_a_score() -> None:
    same_score = _judged("a", at_s=0, road="highway").score()
    assert _judged("b", at_s=0, road="parking lot").score() == same_score


# --- the margin is a real parameter --------------------------------------------


def test_the_tie_margin_has_a_stated_default_and_refuses_nonsense() -> None:
    assert DEFAULT_TIE_EPSILON == 0.02
    with pytest.raises(GeminiSelectionError, match="tie margin"):
        select_judged_candidates((_judged("a", at_s=0, road="highway"),), tie_epsilon=-0.1)


def test_a_zero_margin_ties_only_exact_equals() -> None:
    a = _judged("a", at_s=0, road="highway", interest=0.60, story=0.70)
    b = _judged("b", at_s=600, road="suburban street", interest=0.60, story=0.69)
    hw = _judged("hw", at_s=1200, road="highway", interest=0.60, story=0.70)

    # With a margin, b's variety would win the second pick; with none, hw
    # (an exact equal of a) is the only tied window and is taken instead.
    assert _chosen((a, b, hw), footage_target_s=24.0, tie_epsilon=0.0) == ["a", "hw"]
    assert _chosen((a, b, hw), footage_target_s=24.0) == ["a", "b"]


def test_every_candidate_still_gets_exactly_one_verdict() -> None:
    candidates = tuple(
        _judged(f"w{i}", at_s=i * 30, road="highway" if i % 3 else "street") for i in range(30)
    )

    selection = select_judged_candidates(candidates)

    assert len(selection.verdicts) == 30
    assert {v.event_id for v in selection.verdicts} == {c.event_id for c in candidates}


# --- a place the ride halted at is shown once --------------------------------------


def _museum() -> tuple[JudgedCandidate, ...]:
    """Five well-spaced windows from one long stop, scored above the road."""
    return (
        _judged("road-1", at_s=0.0, road="highway", story=0.7),
        _judged("museum-1", at_s=600.0, road="not applicable", story=0.9, halt=1),
        _judged("museum-2", at_s=900.0, road="not applicable", story=0.9, halt=1),
        _judged("museum-3", at_s=1200.0, road="unknown", story=0.9, halt=1),
        _judged("museum-4", at_s=1500.0, road="not applicable", story=0.8, halt=1),
        _judged("road-2", at_s=2400.0, road="rural", story=0.7),
        _judged("cafe-1", at_s=3000.0, road="parking", story=0.8, halt=2),
    )


def test_one_halt_gets_one_window_however_well_it_scored() -> None:
    chosen = _chosen(_museum(), footage_target_s=60.0)

    assert chosen == ["road-1", "museum-1", "road-2", "cafe-1"]


def test_the_other_windows_of_the_halt_say_why_they_were_left_out() -> None:
    selection = select_judged_candidates(_museum(), footage_target_s=60.0)

    reasons = {v.event_id: v.reason for v in selection.verdicts}
    assert reasons["museum-1"] == REASON_SELECTED
    assert {reasons["museum-2"], reasons["museum-3"], reasons["museum-4"]} == {REASON_SAME_HALT}
    assert selection.to_dict()["reasons"][REASON_SAME_HALT] == 3


def test_windows_on_the_move_are_not_a_halt() -> None:
    """Spacing alone still decides between windows with no halt."""
    candidates = (
        _judged("a", at_s=0.0, road="highway", story=0.9),
        _judged("b", at_s=600.0, road="highway", story=0.9),
    )

    assert _chosen(candidates, footage_target_s=24.0) == ["a", "b"]


def test_a_halt_may_be_allowed_more_than_one_window() -> None:
    chosen = _chosen(_museum(), footage_target_s=60.0, max_windows_per_halt=2)

    assert sum(event_id.startswith("museum") for event_id in chosen) == 2


def test_a_halt_cannot_be_banned_outright() -> None:
    with pytest.raises(GeminiSelectionError, match="at least once"):
        select_judged_candidates(_museum(), max_windows_per_halt=0)


# --- the same picture is not shown twice in a row -----------------------------------


def test_a_window_that_looks_like_its_neighbour_is_left_out_with_a_reason() -> None:
    from app.analysis_look import WindowLook
    from app.gemini_selection import REASON_LOOKS_ALIKE

    candidates = (
        _judged("first", at_s=0.0, road="highway", story=0.9),
        _judged("twin", at_s=600.0, road="highway", story=0.85),
        _judged("other", at_s=1200.0, road="highway", story=0.8),
    )
    grey = WindowLook(110, 128, 128, 12)
    looks = {
        "first": grey,
        "twin": WindowLook(111, 128, 127, 12.4),
        "other": WindowLook(140, 100, 90, 30),
    }

    selection = select_judged_candidates(candidates, footage_target_s=36.0, looks=looks)

    reasons = {v.event_id: v.reason for v in selection.verdicts}
    assert reasons["first"] == REASON_SELECTED
    assert reasons["twin"] == REASON_LOOKS_ALIKE
    assert reasons["other"] == REASON_SELECTED


def test_without_looks_the_selection_is_as_before() -> None:
    candidates = (
        _judged("first", at_s=0.0, road="highway", story=0.9),
        _judged("twin", at_s=600.0, road="highway", story=0.85),
    )
    assert _chosen(candidates, footage_target_s=24.0) == ["first", "twin"]


def test_a_negative_look_alike_distance_is_refused() -> None:
    with pytest.raises(GeminiSelectionError, match="look-alike"):
        select_judged_candidates((_judged("a", at_s=0.0, road="x"),), look_alike=-0.1)
