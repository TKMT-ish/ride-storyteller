"""Synthetic-fixture tests for app.story_audio (research E-5, sound splice)."""

from __future__ import annotations

import math

import pytest

from app.story_audio import (
    CROSSFADE_SECONDS,
    DEFAULT_WIND_ATTENUATION_DB,
    DEFAULT_WIND_THRESHOLD_DB,
    rms_baseline,
    wind_attenuation_db,
    wind_attenuations,
)


def test_crossfade_seconds_is_the_researched_half_second():
    assert CROSSFADE_SECONDS == 0.5


def test_rms_baseline_of_a_single_window_is_itself():
    assert rms_baseline([-30.0]) == -30.0


def test_rms_baseline_is_the_median_not_the_mean_odd_count():
    # One window with wind roaring into the mic (-6, much louder / less
    # negative than the rest) should not drag the baseline toward it.
    assert rms_baseline([-6.0, -32.0, -30.0]) == -30.0


def test_rms_baseline_is_the_median_not_the_mean_even_count():
    assert rms_baseline([-40.0, -30.0, -20.0, -10.0]) == -25.0


def test_rms_baseline_rejects_empty():
    with pytest.raises(ValueError):
        rms_baseline([])


def test_rms_baseline_rejects_positive_dbfs():
    with pytest.raises(ValueError):
        rms_baseline([-20.0, 1.0])


def test_rms_baseline_rejects_non_finite():
    with pytest.raises(ValueError):
        rms_baseline([-20.0, math.nan])
    with pytest.raises(ValueError):
        rms_baseline([-20.0, math.inf])
    with pytest.raises(ValueError):
        rms_baseline([-20.0, -math.inf])


def test_attenuation_is_zero_at_the_baseline():
    assert wind_attenuation_db(-30.0, -30.0) == 0.0


def test_attenuation_is_zero_for_a_quieter_than_baseline_window():
    # Coasting, or waiting at a light -- quieter is not a defect to fix.
    assert wind_attenuation_db(-40.0, -30.0) == 0.0


def test_attenuation_is_zero_just_under_the_threshold():
    got = wind_attenuation_db(-24.01, -30.0, threshold_db=6.0)
    assert got == 0.0


def test_attenuation_applies_at_exactly_the_threshold():
    got = wind_attenuation_db(-24.0, -30.0, threshold_db=6.0)
    assert got == DEFAULT_WIND_ATTENUATION_DB


def test_attenuation_applies_flat_not_proportional_when_over_threshold():
    # A window 20 dB over baseline is pulled down by the same flat amount
    # as one just at the threshold -- this is a severe/not-severe call,
    # not a proportional correction.
    quiet_over = wind_attenuation_db(-24.0, -30.0, threshold_db=6.0)
    loud_over = wind_attenuation_db(-5.0, -30.0, threshold_db=6.0)
    assert quiet_over == loud_over == DEFAULT_WIND_ATTENUATION_DB


def test_attenuation_respects_custom_threshold_and_attenuation():
    got = wind_attenuation_db(-20.0, -30.0, threshold_db=10.0, attenuation_db=-3.0)
    assert got == -3.0
    still_under = wind_attenuation_db(-21.0, -30.0, threshold_db=10.0, attenuation_db=-3.0)
    assert still_under == 0.0


def test_attenuation_rejects_non_finite_or_positive_rms_or_baseline():
    with pytest.raises(ValueError):
        wind_attenuation_db(1.0, -30.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(-30.0, 1.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(math.nan, -30.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(-30.0, math.inf)
    with pytest.raises(ValueError):
        wind_attenuation_db(-math.inf, -30.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(-30.0, -math.inf)


def test_attenuation_rejects_non_positive_threshold():
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, threshold_db=0.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, threshold_db=-1.0)


def test_attenuation_rejects_non_finite_threshold():
    # A positive but non-finite threshold passes the `<= 0` half of the
    # check; this pins the `isfinite` half is also enforced, not skipped.
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, threshold_db=math.nan)
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, threshold_db=math.inf)


def test_attenuation_rejects_non_negative_attenuation():
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, attenuation_db=0.0)
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, attenuation_db=3.0)


def test_attenuation_rejects_non_finite_attenuation():
    # A negative but non-finite attenuation passes the `>= 0` half of the
    # check; this pins the `isfinite` half is also enforced, not skipped.
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, attenuation_db=math.nan)
    with pytest.raises(ValueError):
        wind_attenuation_db(-24.0, -30.0, attenuation_db=-math.inf)


def test_attenuations_default_to_the_groups_own_median_baseline():
    rms_values = [-40.0, -30.0, -20.0]
    got = wind_attenuations(rms_values)
    assert got == tuple(wind_attenuation_db(v, -30.0) for v in rms_values)


def test_attenuations_uniform_group_is_all_zero():
    got = wind_attenuations([-28.0, -28.0, -28.0])
    assert got == (0.0, 0.0, 0.0)


def test_attenuations_preserve_input_order():
    rms_values = [-5.0, -40.0, -30.0]
    got = wind_attenuations(rms_values)
    assert len(got) == 3
    # The wind-heavy window (-5) is the only one pulled down, matched up
    # by position, not by sorted value.
    assert got[0] == DEFAULT_WIND_ATTENUATION_DB
    assert got[1] == 0.0
    assert got[2] == 0.0


def test_attenuations_can_target_an_explicit_baseline_not_in_the_group():
    rms_values = [-25.0, -24.0]
    got = wind_attenuations(rms_values, baseline=-40.0)
    assert all(v == DEFAULT_WIND_ATTENUATION_DB for v in got)
    assert got != wind_attenuations(rms_values)


def test_attenuations_rejects_empty():
    with pytest.raises(ValueError):
        wind_attenuations([])


def test_default_threshold_and_attenuation_match_research_figures():
    assert DEFAULT_WIND_THRESHOLD_DB == 6.0
    assert DEFAULT_WIND_ATTENUATION_DB == -6.0
