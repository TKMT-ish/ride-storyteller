"""Tests for summing climb and descent without the barometer's jitter."""

from __future__ import annotations

import pytest

from app.gps.elevation import gain_and_loss


def test_a_real_climb_is_counted_in_full() -> None:
    assert gain_and_loss([100, 150, 200, 300]) == (200.0, 0.0)


def test_jitter_on_flat_ground_counts_for_nothing() -> None:
    wobble = [100 + (3 if i % 2 else -3) for i in range(200)]
    assert gain_and_loss(wobble) == (0.0, 0.0)


def test_jitter_on_a_climb_does_not_inflate_it() -> None:
    climb = [100 + i * 2 + (3 if i % 2 else -3) for i in range(100)]
    gain, loss = gain_and_loss(climb)
    assert 190.0 <= gain <= 210.0
    assert loss == 0.0


def test_a_descent_after_a_climb_is_both() -> None:
    gain, loss = gain_and_loss([0, 500, 1000, 500, 0])
    assert (gain, loss) == (1000.0, 1000.0)


def test_missing_heights_are_skipped_and_nonsense_refused() -> None:
    assert gain_and_loss([None, 100, None, 200]) == (100.0, 0.0)
    assert gain_and_loss([]) == (0.0, 0.0)
    with pytest.raises(ValueError):
        gain_and_loss([1, 2], hysteresis_m=-1.0)
