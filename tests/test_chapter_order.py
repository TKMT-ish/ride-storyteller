"""Synthetic-fixture tests for E-1's within-chapter ordering."""

from __future__ import annotations

import pytest

from app.chapter_order import ChapterOrderError, ChapterWindow, order_chapter_windows


def test_a_lone_window_is_its_own_order() -> None:
    assert order_chapter_windows((ChapterWindow("a", 3.0),)) == ("a",)


def test_the_opener_plays_first_even_if_it_moves_the_least() -> None:
    windows = (
        ChapterWindow("busiest", 9.0),
        ChapterWindow("opener", 1.0, opens_chapter=True),
        ChapterWindow("mid", 5.0),
    )
    order = order_chapter_windows(windows)
    assert order[0] == "opener"


def test_with_no_opener_the_whole_chapter_zigzags_by_motion() -> None:
    windows = tuple(ChapterWindow(f"w{i}", float(i)) for i in range(5))
    # motions 0..4 sorted high->low is w4,w3,w2,w1,w0; dealt alternately
    # from the top and bottom of that list: w4, w0, w3, w1, w2.
    assert order_chapter_windows(windows) == ("w4", "w0", "w3", "w1", "w2")


def test_two_windows_after_the_opener_go_high_then_low() -> None:
    windows = (
        ChapterWindow("opener", 4.0, opens_chapter=True),
        ChapterWindow("calm", 1.0),
        ChapterWindow("busy", 8.0),
    )
    assert order_chapter_windows(windows) == ("opener", "busy", "calm")


def test_a_lone_window_that_is_also_the_opener_is_still_its_own_order() -> None:
    windows = (ChapterWindow("only", 3.0, opens_chapter=True),)
    assert order_chapter_windows(windows) == ("only",)


def test_two_windows_with_no_opener_zigzag_high_then_low() -> None:
    windows = (ChapterWindow("x", 1.0), ChapterWindow("y", 5.0))
    assert order_chapter_windows(windows) == ("y", "x")


def test_an_even_count_with_no_opener_still_zigzags_to_the_end() -> None:
    windows = tuple(ChapterWindow(f"w{i}", float(i)) for i in range(4))
    # motions 0..3 sorted high->low is w3,w2,w1,w0; dealt alternately from
    # the top and bottom of that list: w3, w0, w2, w1.
    assert order_chapter_windows(windows) == ("w3", "w0", "w2", "w1")


def test_no_run_of_three_shares_the_same_side_of_the_motion_split() -> None:
    windows = tuple(ChapterWindow(f"w{i}", float(i)) for i in range(9))
    order = order_chapter_windows(windows)
    motions = {w.window_id: w.motion for w in windows}
    median = sorted(motions.values())[len(motions) // 2]
    sides = ["high" if motions[window_id] >= median else "low" for window_id in order]
    for a, b, c in zip(sides, sides[1:], sides[2:], strict=False):
        assert not (a == b == c)


def test_ties_in_motion_break_on_window_id_so_order_is_deterministic() -> None:
    windows = (
        ChapterWindow("b", 5.0),
        ChapterWindow("a", 5.0),
        ChapterWindow("c", 5.0),
    )
    first = order_chapter_windows(windows)
    second = order_chapter_windows(tuple(reversed(windows)))
    assert first == second


def test_a_three_way_motion_tie_zigzags_by_id_not_by_input_order() -> None:
    # by_motion sorts equal motions ascending by id (a, b, c), then the
    # zigzag deals from the low end first: a, then c, then b.
    windows = (
        ChapterWindow("b", 5.0),
        ChapterWindow("a", 5.0),
        ChapterWindow("c", 5.0),
    )
    assert order_chapter_windows(windows) == ("a", "c", "b")


def test_an_empty_chapter_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        order_chapter_windows(())


def test_duplicate_window_ids_are_refused() -> None:
    with pytest.raises(ChapterOrderError):
        order_chapter_windows((ChapterWindow("a", 1.0), ChapterWindow("a", 2.0)))


def test_two_openers_are_refused() -> None:
    with pytest.raises(ChapterOrderError):
        order_chapter_windows(
            (
                ChapterWindow("a", 1.0, opens_chapter=True),
                ChapterWindow("b", 2.0, opens_chapter=True),
            )
        )


def test_duplicate_ids_are_caught_before_the_opener_count_is_checked() -> None:
    # Both faults are present at once (same id used by both self-declared
    # openers); the id check runs first, so that is the message that
    # surfaces, not "at most one window can open a chapter".
    with pytest.raises(ChapterOrderError, match="unique"):
        order_chapter_windows(
            (
                ChapterWindow("a", 1.0, opens_chapter=True),
                ChapterWindow("a", 2.0, opens_chapter=True),
            )
        )


def test_negative_motion_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        ChapterWindow("a", -1.0)


def test_zero_motion_is_accepted_as_the_non_negative_boundary() -> None:
    assert ChapterWindow("a", 0.0).motion == 0.0


def test_negative_zero_motion_is_accepted_since_it_is_not_less_than_zero() -> None:
    # -0.0 < 0 is False in Python, so this is not the negative-motion case.
    assert ChapterWindow("a", -0.0).motion == 0.0


def test_non_finite_motion_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        ChapterWindow("a", float("nan"))


def test_positive_infinite_motion_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        ChapterWindow("a", float("inf"))


def test_negative_infinite_motion_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        ChapterWindow("a", float("-inf"))


def test_empty_window_id_is_refused() -> None:
    with pytest.raises(ChapterOrderError):
        ChapterWindow("", 1.0)
