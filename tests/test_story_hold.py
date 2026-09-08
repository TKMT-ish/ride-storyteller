"""Synthetic-fixture tests for E-2's motion-widened hold ranges."""

from __future__ import annotations

import math

import pytest

from app.story_hold import (
    DEFAULT_HALF_DURATION_S,
    LONG_HOLD_RANGE_S,
    MEDIUM_HOLD_RANGE_S,
    SHORT_HOLD_RANGE_S,
    StoryHoldError,
    WindowHalf,
    choose_half_by_motion,
    hold_all_from_motion,
    hold_from_motion,
    hold_range_for,
    motion_by_half,
    trim_bounds_for_half,
)

# --- hold_range_for ------------------------------------------------------


def test_top_ranks_earn_the_long_range() -> None:
    assert hold_range_for(1) == LONG_HOLD_RANGE_S
    assert hold_range_for(5) == LONG_HOLD_RANGE_S


def test_the_rest_of_the_model_ranking_earns_the_medium_range() -> None:
    assert hold_range_for(6) == MEDIUM_HOLD_RANGE_S
    assert hold_range_for(200) == MEDIUM_HOLD_RANGE_S


def test_unranked_windows_earn_the_short_connector_range() -> None:
    assert hold_range_for(None) == SHORT_HOLD_RANGE_S


# --- hold_from_motion ------------------------------------------------------


def test_motion_at_the_floor_gets_the_shortest_end_of_the_tier() -> None:
    hold = hold_from_motion(1, 2.0, motion_floor=2.0, motion_ceiling=8.0)
    assert hold == LONG_HOLD_RANGE_S[0]


def test_motion_at_the_ceiling_gets_the_longest_end_of_the_tier() -> None:
    hold = hold_from_motion(1, 8.0, motion_floor=2.0, motion_ceiling=8.0)
    assert hold == LONG_HOLD_RANGE_S[1]


def test_motion_halfway_lands_at_the_tiers_midpoint() -> None:
    hold = hold_from_motion(None, 5.0, motion_floor=2.0, motion_ceiling=8.0)
    low, high = SHORT_HOLD_RANGE_S
    assert hold == pytest.approx((low + high) / 2)


def test_a_floor_equal_to_the_ceiling_places_every_window_at_the_midpoint() -> None:
    low, high = MEDIUM_HOLD_RANGE_S
    hold = hold_from_motion(10, 4.0, motion_floor=4.0, motion_ceiling=4.0)
    assert hold == pytest.approx((low + high) / 2)


def test_motion_below_the_floor_is_clamped_not_extrapolated() -> None:
    hold = hold_from_motion(1, 0.0, motion_floor=2.0, motion_ceiling=8.0)
    assert hold == LONG_HOLD_RANGE_S[0]


def test_motion_above_the_ceiling_is_clamped_not_extrapolated() -> None:
    hold = hold_from_motion(1, 100.0, motion_floor=2.0, motion_ceiling=8.0)
    assert hold == LONG_HOLD_RANGE_S[1]


def test_negative_motion_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, -1.0, motion_floor=0.0, motion_ceiling=8.0)


def test_negative_motion_floor_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 1.0, motion_floor=-1.0, motion_ceiling=8.0)


def test_a_ceiling_below_its_floor_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 1.0, motion_floor=8.0, motion_ceiling=2.0)


def test_zero_motion_including_negative_zero_is_accepted() -> None:
    # -0.0 < 0 is False in Python, same non-trap as app.chapter_order's own
    # motion boundary -- a window that does not move at all must not be
    # refused just because its reading came back as negative zero.
    assert hold_from_motion(1, -0.0, motion_floor=0.0, motion_ceiling=8.0) == LONG_HOLD_RANGE_S[0]
    assert hold_from_motion(1, 4.0, motion_floor=-0.0, motion_ceiling=8.0) == pytest.approx(9.0)


def test_a_nan_motion_is_refused_rather_than_silently_clamped() -> None:
    # Without an explicit finiteness check, NaN would sail past `< 0`
    # (every comparison with NaN is False) and, once clamped by min/max
    # further down, quietly resolve to the tier's low end -- a wrong
    # answer with no error, unlike sibling app.chapter_order and this same
    # module's own motion_by_half, both of which already reject NaN.
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, math.nan, motion_floor=0.0, motion_ceiling=8.0)


def test_an_infinite_motion_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, math.inf, motion_floor=0.0, motion_ceiling=8.0)


def test_a_nan_or_infinite_floor_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 4.0, motion_floor=math.nan, motion_ceiling=8.0)
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 4.0, motion_floor=-math.inf, motion_ceiling=8.0)


def test_a_nan_or_infinite_ceiling_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 4.0, motion_floor=0.0, motion_ceiling=math.nan)
    with pytest.raises(StoryHoldError):
        hold_from_motion(1, 4.0, motion_floor=0.0, motion_ceiling=math.inf)


# --- hold_all_from_motion ------------------------------------------------------


def test_an_empty_set_holds_nothing() -> None:
    assert hold_all_from_motion(()) == {}


def test_a_lone_window_is_held_at_its_tiers_midpoint() -> None:
    low, high = SHORT_HOLD_RANGE_S
    holds = hold_all_from_motion((("a", None, 3.0),))
    assert holds == {"a": pytest.approx((low + high) / 2)}


def test_motion_places_each_window_within_its_own_tiers_range() -> None:
    holds = hold_all_from_motion(
        (
            ("still", 1, 1.0),
            ("busy", 1, 9.0),
            ("cutaway-calm", None, 1.0),
            ("cutaway-busy", None, 9.0),
        )
    )
    assert holds["still"] == LONG_HOLD_RANGE_S[0]
    assert holds["busy"] == LONG_HOLD_RANGE_S[1]
    assert holds["cutaway-calm"] == SHORT_HOLD_RANGE_S[0]
    assert holds["cutaway-busy"] == SHORT_HOLD_RANGE_S[1]


def test_three_equal_holds_in_a_row_are_broken_up() -> None:
    ranked_motions = (
        ("a", None, 5.0),
        ("b", None, 5.0),
        ("c", None, 5.0),
        ("d", None, 5.0),
        ("e", None, 1.0),
    )

    holds = hold_all_from_motion(ranked_motions)

    ordered = [holds[event_id] for event_id, _, _ in ranked_motions]
    assert not any(a == b == c for a, b, c in zip(ordered, ordered[1:], ordered[2:], strict=False))
    # a, c and d still sit at their tier's high end (they moved the most);
    # only the middle of the run of three (b) is pushed to the low end.
    assert ordered[0] == ordered[2] == ordered[3] == SHORT_HOLD_RANGE_S[1]
    assert ordered[1] == SHORT_HOLD_RANGE_S[0]
    assert ordered[4] == SHORT_HOLD_RANGE_S[0]


def test_the_break_up_never_touches_the_first_or_last_window() -> None:
    # Every window moves alike, so every hold starts at its tier's
    # midpoint (floor equals ceiling); only an interior window (never
    # the first or last, which have no run of three to sit inside) can
    # be nudged off that tie.
    ranked_motions = tuple((f"w{i}", None, 5.0) for i in range(4))
    low, high = SHORT_HOLD_RANGE_S
    midpoint = (low + high) / 2

    holds = hold_all_from_motion(ranked_motions)

    assert holds["w0"] == pytest.approx(midpoint)
    assert holds["w3"] == pytest.approx(midpoint)
    assert holds["w1"] == high


def test_invalid_motion_inside_the_set_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_all_from_motion((("a", None, -1.0), ("b", None, 2.0)))


def test_a_nan_motion_inside_the_set_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        hold_all_from_motion((("a", None, math.nan), ("b", None, 2.0)))


# --- motion_by_half ------------------------------------------------------


def test_an_even_series_splits_down_the_middle() -> None:
    first, second = motion_by_half([1.0, 1.0, 1.0, 5.0, 5.0, 5.0])
    assert first == pytest.approx(1.0)
    assert second == pytest.approx(5.0)


def test_an_odd_series_gives_the_extra_reading_to_the_second_half() -> None:
    # Five readings split 2/3: the middle one joins the second half rather
    # than the first getting the extra sample by construction.
    first, second = motion_by_half([0.0, 0.0, 9.0, 9.0, 9.0])
    assert first == pytest.approx(0.0)
    assert second == pytest.approx(9.0)


def test_a_single_reading_cannot_be_split() -> None:
    with pytest.raises(StoryHoldError):
        motion_by_half([1.0])


def test_an_empty_series_cannot_be_split() -> None:
    with pytest.raises(StoryHoldError):
        motion_by_half([])


def test_a_negative_reading_inside_the_series_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        motion_by_half([1.0, -1.0, 1.0, 1.0])


def test_a_nan_or_infinite_reading_inside_the_series_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        motion_by_half([1.0, math.nan, 1.0, 1.0])
    with pytest.raises(StoryHoldError):
        motion_by_half([1.0, math.inf, 1.0, 1.0])


# --- choose_half_by_motion ------------------------------------------------------


def test_a_busier_second_half_is_chosen() -> None:
    assert choose_half_by_motion([1.0, 1.0, 1.0, 8.0, 8.0, 8.0]) is WindowHalf.SECOND


def test_a_busier_first_half_is_chosen() -> None:
    assert choose_half_by_motion([8.0, 8.0, 8.0, 1.0, 1.0, 1.0]) is WindowHalf.FIRST


def test_a_tie_keeps_the_first_half() -> None:
    assert choose_half_by_motion([4.0, 4.0, 4.0, 4.0]) is WindowHalf.FIRST


def test_a_window_that_barely_moves_at_all_still_keeps_the_first_half() -> None:
    assert choose_half_by_motion([0.0, 0.0, 0.0, 0.0]) is WindowHalf.FIRST


# --- trim_bounds_for_half ------------------------------------------------------


def test_the_first_half_starts_at_the_windows_own_start() -> None:
    assert trim_bounds_for_half(12.0, WindowHalf.FIRST) == (0.0, DEFAULT_HALF_DURATION_S)


def test_the_second_half_ends_at_the_windows_own_end() -> None:
    start, end = trim_bounds_for_half(12.0, WindowHalf.SECOND)
    assert (start, end) == (12.0 - DEFAULT_HALF_DURATION_S, 12.0)


def test_a_custom_half_duration_is_honoured() -> None:
    assert trim_bounds_for_half(12.0, WindowHalf.FIRST, half_duration_s=4.0) == (0.0, 4.0)


def test_a_window_no_longer_than_the_half_uses_all_of_it_either_way() -> None:
    # A four-second window cannot give up six spare seconds; both halves
    # clamp to the whole window rather than asking for time it lacks.
    assert trim_bounds_for_half(4.0, WindowHalf.FIRST) == (0.0, 4.0)
    assert trim_bounds_for_half(4.0, WindowHalf.SECOND) == (0.0, 4.0)


def test_a_window_exactly_as_long_as_the_half_uses_all_of_it() -> None:
    assert trim_bounds_for_half(6.0, WindowHalf.FIRST) == (0.0, 6.0)
    assert trim_bounds_for_half(6.0, WindowHalf.SECOND) == (0.0, 6.0)


def test_a_non_positive_window_duration_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        trim_bounds_for_half(0.0, WindowHalf.FIRST)


def test_a_non_positive_half_duration_is_refused() -> None:
    with pytest.raises(StoryHoldError):
        trim_bounds_for_half(12.0, WindowHalf.FIRST, half_duration_s=0.0)
