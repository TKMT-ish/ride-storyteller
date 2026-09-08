"""Synthetic-fixture tests for app.story_timelapse (research E-7, timelapse fill)."""

from __future__ import annotations

import math

import pytest

from app.story_timelapse import (
    MAXIMUM_DISPLAY_S,
    MINIMUM_DISPLAY_S,
    MINIMUM_GAP_S,
    MINIMUM_HALT_S,
    TimelapseDecision,
    TimelapseDecisionError,
    TimelapseSourceKind,
    decide_timelapse,
    decide_timelapses,
    is_timelapse_candidate,
    timelapse_display_s,
)


def test_research_thresholds_and_display_bounds():
    assert MINIMUM_HALT_S == 15 * 60.0
    assert MINIMUM_GAP_S == 60.0
    assert MINIMUM_DISPLAY_S == 3.0
    assert MAXIMUM_DISPLAY_S == 5.0


def test_a_halt_under_the_long_halt_threshold_is_not_a_candidate():
    assert not is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, MINIMUM_HALT_S - 1.0)


def test_a_halt_at_exactly_the_threshold_is_a_candidate():
    assert is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, MINIMUM_HALT_S)


def test_a_five_minute_lunch_stop_is_not_a_long_halt_candidate():
    # Research's own example of what should stay a plain stop.
    assert not is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, 5 * 60.0)


def test_a_gap_uses_the_shorter_card_earning_threshold_not_the_halt_one():
    just_over_gap_minimum = MINIMUM_GAP_S + 1.0
    assert just_over_gap_minimum < MINIMUM_HALT_S
    assert is_timelapse_candidate(TimelapseSourceKind.UNFILMED_GAP, just_over_gap_minimum)
    assert not is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, just_over_gap_minimum)


def test_a_gap_at_exactly_its_own_threshold_is_a_candidate():
    assert is_timelapse_candidate(TimelapseSourceKind.UNFILMED_GAP, MINIMUM_GAP_S)


def test_a_gap_just_under_its_own_threshold_is_not():
    assert not is_timelapse_candidate(TimelapseSourceKind.UNFILMED_GAP, MINIMUM_GAP_S - 0.01)


def test_is_timelapse_candidate_rejects_non_finite_or_negative_duration():
    with pytest.raises(TimelapseDecisionError):
        is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, -1.0)
    with pytest.raises(TimelapseDecisionError):
        is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, math.nan)
    with pytest.raises(TimelapseDecisionError):
        is_timelapse_candidate(TimelapseSourceKind.LONG_HALT, math.inf)


def test_display_length_at_zero_duration_is_the_minimum():
    assert timelapse_display_s(0.0) == MINIMUM_DISPLAY_S


def test_display_length_at_or_past_saturation_is_the_maximum():
    assert timelapse_display_s(3600.0) == MAXIMUM_DISPLAY_S
    assert timelapse_display_s(7200.0) == MAXIMUM_DISPLAY_S


def test_display_length_is_linear_at_the_midpoint():
    got = timelapse_display_s(1800.0)
    assert got == pytest.approx((MINIMUM_DISPLAY_S + MAXIMUM_DISPLAY_S) / 2)


def test_display_length_honours_custom_bounds_and_saturation():
    got = timelapse_display_s(
        50.0, minimum_display_s=2.0, maximum_display_s=4.0, saturates_at_s=100.0
    )
    assert got == pytest.approx(3.0)


def test_display_length_rejects_non_finite_or_negative_duration():
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(-1.0)
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(math.nan)


def test_display_length_rejects_non_positive_minimum():
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, minimum_display_s=0.0)
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, minimum_display_s=-1.0)


def test_display_length_rejects_maximum_at_or_below_minimum():
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, minimum_display_s=4.0, maximum_display_s=4.0)
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, minimum_display_s=4.0, maximum_display_s=3.0)


def test_display_length_rejects_non_positive_saturation():
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, saturates_at_s=0.0)
    with pytest.raises(TimelapseDecisionError):
        timelapse_display_s(10.0, saturates_at_s=-100.0)


def test_decide_timelapse_returns_none_below_threshold():
    assert decide_timelapse(TimelapseSourceKind.LONG_HALT, 5 * 60.0) is None
    assert decide_timelapse(TimelapseSourceKind.UNFILMED_GAP, 10.0) is None


def test_decide_timelapse_returns_a_decision_at_or_above_threshold():
    got = decide_timelapse(TimelapseSourceKind.LONG_HALT, MINIMUM_HALT_S)
    assert got == TimelapseDecision(
        kind=TimelapseSourceKind.LONG_HALT,
        source_duration_s=MINIMUM_HALT_S,
        display_s=timelapse_display_s(MINIMUM_HALT_S),
    )


def test_decide_timelapse_returns_a_decision_for_an_unfilmed_gap_too():
    # The two kinds share decide_timelapse's body but use different
    # candidacy thresholds (test_a_gap_uses_the_shorter... above) -- check
    # the UNFILMED_GAP branch gets the same full equality treatment, not
    # just the "is not None" spot-check decide_timelapses's test gives it.
    got = decide_timelapse(TimelapseSourceKind.UNFILMED_GAP, MINIMUM_GAP_S)
    assert got == TimelapseDecision(
        kind=TimelapseSourceKind.UNFILMED_GAP,
        source_duration_s=MINIMUM_GAP_S,
        display_s=timelapse_display_s(MINIMUM_GAP_S),
    )


def test_decision_rejects_non_finite_or_negative_source_duration():
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(kind=TimelapseSourceKind.LONG_HALT, source_duration_s=-1.0, display_s=3.0)
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(
            kind=TimelapseSourceKind.LONG_HALT, source_duration_s=math.nan, display_s=3.0
        )
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(
            kind=TimelapseSourceKind.LONG_HALT, source_duration_s=math.inf, display_s=3.0
        )


def test_decision_rejects_non_positive_or_non_finite_display_s():
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(
            kind=TimelapseSourceKind.LONG_HALT, source_duration_s=1000.0, display_s=0.0
        )
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(
            kind=TimelapseSourceKind.LONG_HALT, source_duration_s=1000.0, display_s=-3.0
        )
    with pytest.raises(TimelapseDecisionError):
        TimelapseDecision(
            kind=TimelapseSourceKind.LONG_HALT, source_duration_s=1000.0, display_s=math.nan
        )


def test_decide_timelapses_preserves_order_and_marks_non_candidates_none():
    spans = [
        (TimelapseSourceKind.LONG_HALT, 5 * 60.0),  # too short: None
        (TimelapseSourceKind.LONG_HALT, MINIMUM_HALT_S),
        (TimelapseSourceKind.UNFILMED_GAP, MINIMUM_GAP_S),
    ]
    got = decide_timelapses(spans)
    assert len(got) == 3
    assert got[0] is None
    assert got[1] is not None and got[1].kind is TimelapseSourceKind.LONG_HALT
    assert got[2] is not None and got[2].kind is TimelapseSourceKind.UNFILMED_GAP


def test_decide_timelapses_rejects_empty():
    with pytest.raises(TimelapseDecisionError):
        decide_timelapses([])


def test_decide_timelapses_all_none_when_every_span_is_under_threshold():
    spans = [
        (TimelapseSourceKind.LONG_HALT, 5 * 60.0),
        (TimelapseSourceKind.UNFILMED_GAP, 10.0),
    ]
    got = decide_timelapses(spans)
    assert got == (None, None)


def test_decide_timelapses_propagates_a_span_s_validation_error():
    # A single bad span (research's own units are seconds; a negative one
    # is a caller bug, not "no timelapse") should fail the whole day's plan
    # rather than silently skipping it -- decide_timelapses makes no attempt
    # to catch and continue past a span it cannot evaluate.
    spans = [
        (TimelapseSourceKind.LONG_HALT, MINIMUM_HALT_S),
        (TimelapseSourceKind.UNFILMED_GAP, -1.0),
    ]
    with pytest.raises(TimelapseDecisionError):
        decide_timelapses(spans)
