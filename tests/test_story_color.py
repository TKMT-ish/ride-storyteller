"""Synthetic-fixture tests for app.story_color (research E-6, exposure)."""

from __future__ import annotations

import math

import pytest

from app.story_color import (
    DEFAULT_MAX_BRIGHTNESS_CORRECTION,
    brightness_correction,
    brightness_corrections,
    luma_target,
)


def test_luma_target_of_a_single_window_is_itself():
    assert luma_target([120.0]) == 120.0


def test_luma_target_is_the_median_not_the_mean_odd_count():
    # One badly under-exposed window (10) should not drag the target
    # down the way a mean would.
    assert luma_target([10.0, 118.0, 122.0]) == 118.0


def test_luma_target_is_the_median_not_the_mean_even_count():
    assert luma_target([100.0, 120.0, 140.0, 160.0]) == 130.0


def test_luma_target_rejects_empty():
    with pytest.raises(ValueError):
        luma_target([])


def test_luma_target_rejects_negative_luma():
    with pytest.raises(ValueError):
        luma_target([100.0, -1.0])


def test_luma_target_rejects_non_finite_luma():
    with pytest.raises(ValueError):
        luma_target([100.0, math.nan])
    with pytest.raises(ValueError):
        luma_target([100.0, math.inf])


def test_correction_is_zero_at_the_target():
    assert brightness_correction(120.0, 120.0) == 0.0


def test_correction_brightens_a_dark_window():
    # Small enough gap to stay well inside the default cap.
    got = brightness_correction(100.0, 110.0)
    assert got == pytest.approx((110.0 - 100.0) / 255.0)
    assert got > 0


def test_correction_dims_a_bright_window():
    got = brightness_correction(150.0, 140.0)
    assert got == pytest.approx((140.0 - 150.0) / 255.0)
    assert got < 0


def test_correction_clamps_a_very_dark_window():
    got = brightness_correction(10.0, 200.0)
    assert got == DEFAULT_MAX_BRIGHTNESS_CORRECTION


def test_correction_clamps_a_very_bright_window():
    got = brightness_correction(240.0, 10.0)
    assert got == -DEFAULT_MAX_BRIGHTNESS_CORRECTION


def test_correction_respects_a_custom_cap():
    got = brightness_correction(0.0, 255.0, max_correction=0.5)
    assert got == 0.5


def test_correction_rejects_non_positive_cap():
    with pytest.raises(ValueError):
        brightness_correction(100.0, 110.0, max_correction=0.0)
    with pytest.raises(ValueError):
        brightness_correction(100.0, 110.0, max_correction=-0.1)


def test_correction_rejects_non_finite_cap():
    # A positive but non-finite cap passes the `<= 0` half of the check;
    # this pins the `isfinite` half is also enforced, not skipped.
    with pytest.raises(ValueError):
        brightness_correction(100.0, 110.0, max_correction=math.nan)
    with pytest.raises(ValueError):
        brightness_correction(100.0, 110.0, max_correction=math.inf)


def test_correction_rejects_negative_or_non_finite_inputs():
    with pytest.raises(ValueError):
        brightness_correction(-1.0, 100.0)
    with pytest.raises(ValueError):
        brightness_correction(100.0, math.nan)
    with pytest.raises(ValueError):
        brightness_correction(math.inf, 100.0)
    with pytest.raises(ValueError):
        brightness_correction(100.0, -1.0)
    with pytest.raises(ValueError):
        brightness_correction(100.0, math.inf)


def test_corrections_default_to_the_groups_own_median_target():
    lumas = [80.0, 100.0, 120.0]
    got = brightness_corrections(lumas)
    assert got == tuple(brightness_correction(v, 100.0) for v in lumas)


def test_corrections_uniform_group_is_all_zero():
    got = brightness_corrections([90.0, 90.0, 90.0])
    assert got == (0.0, 0.0, 0.0)


def test_corrections_preserve_input_order():
    lumas = [200.0, 50.0, 125.0]
    got = brightness_corrections(lumas)
    assert len(got) == 3
    # The dark window (50) gets a positive push, the bright one (200) a
    # negative one, matched up by position, not by sorted value.
    assert got[0] < 0
    assert got[1] > 0


def test_corrections_can_target_an_explicit_value_not_in_the_group():
    lumas = [100.0, 110.0]
    got = brightness_corrections(lumas, target=200.0)
    assert all(v > 0 for v in got)
    assert got != brightness_corrections(lumas)


def test_corrections_rejects_empty():
    with pytest.raises(ValueError):
        brightness_corrections([])
