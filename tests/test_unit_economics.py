"""The per-ride spend, against what a hundred or three hundred yen a month allows."""

from __future__ import annotations

import pytest

from app.unit_economics import (
    ESTIMATED_STORAGE_JPY_PER_RIDE,
    MEASURED_JUDGE_JPY_PER_WINDOW,
    MEASURED_RANK_JPY_PER_WINDOW,
    TIER_100,
    TIER_300,
    TIERS,
    PriceTier,
    RideCost,
    UnitEconomicsError,
    cheapest_fitting_tier,
    current_pipeline,
    ranking_only_pipeline,
)


def test_the_rates_are_the_measured_ones() -> None:
    """173 windows cost 25.56 yen; 40 ranked cost 2.25. Change with a new measurement."""
    assert 173 * MEASURED_JUDGE_JPY_PER_WINDOW == pytest.approx(25.6, abs=0.1)
    assert 40 * MEASURED_RANK_JPY_PER_WINDOW == pytest.approx(2.25, abs=0.05)


def test_a_tier_leaves_the_model_what_the_margin_does_not_take() -> None:
    assert TIER_100.ceiling_jpy_per_ride == pytest.approx(7.5)
    assert TIER_300.ceiling_jpy_per_ride == pytest.approx(22.5)
    assert PriceTier("t", 300.0, rides_per_month=8).ceiling_jpy_per_ride == pytest.approx(11.25)


def test_the_pipeline_that_runs_today_does_not_fit_either_tier() -> None:
    """What the first real ride cost, and why Gate 7 exists."""
    cost = current_pipeline(173)

    assert cost.total_jpy == pytest.approx(25.6 + 2.24 + 0.4, abs=0.2)
    assert not cost.fits(TIER_100)
    assert not cost.fits(TIER_300)
    assert cheapest_fitting_tier(cost) is None


def test_ranking_alone_at_a_sixty_second_stride_fits_the_hundred_yen_tier() -> None:
    """The lever Gate 7 reaches for first."""
    cost = ranking_only_pipeline(87)

    assert cost.judge_jpy == 0.0
    assert cost.total_jpy == pytest.approx(5.6 + 0.4, abs=0.3)
    assert cost.fits(TIER_100)
    assert cheapest_fitting_tier(cost) is TIER_100


def test_ranking_alone_at_the_current_stride_fits_only_the_three_hundred_tier() -> None:
    cost = ranking_only_pipeline(173)

    assert not cost.fits(TIER_100)
    assert cost.fits(TIER_300)
    assert cheapest_fitting_tier(cost) is TIER_300


def test_the_payload_carries_the_figures_and_the_fit_and_nothing_else() -> None:
    payload = current_pipeline(173).to_dict()

    assert set(payload) == {
        "schema_version",
        "judged_windows",
        "ranked_windows",
        "judge_jpy",
        "rank_jpy",
        "storage_jpy",
        "total_jpy",
        "tiers",
    }
    assert payload["tiers"]["tier-100"]["fits"] is False
    assert payload["tiers"]["tier-100"]["ceiling_jpy_per_ride"] == 7.5


def test_nonsense_is_refused() -> None:
    with pytest.raises(UnitEconomicsError):
        PriceTier("t", 0.0)
    with pytest.raises(UnitEconomicsError):
        PriceTier("t", 100.0, gross_margin=1.0)
    with pytest.raises(UnitEconomicsError):
        RideCost(judged_windows=-1, ranked_windows=0)


def test_a_tier_needs_at_least_one_ride_a_month() -> None:
    with pytest.raises(UnitEconomicsError):
        PriceTier("t", 100.0, rides_per_month=0)
    with pytest.raises(UnitEconomicsError):
        PriceTier("t", 100.0, rides_per_month=-1)


def test_a_negative_margin_is_refused_the_same_as_a_margin_of_one() -> None:
    """The check is a range, not just an upper bound."""
    with pytest.raises(UnitEconomicsError):
        PriceTier("t", 100.0, gross_margin=-0.01)


def test_a_margin_of_zero_keeps_the_whole_price_for_the_model() -> None:
    """The lower edge of the accepted range is itself accepted."""
    tier = PriceTier("t", 100.0, gross_margin=0.0, rides_per_month=4)
    assert tier.ceiling_jpy_per_ride == pytest.approx(25.0)


def test_ranked_windows_cannot_be_negative_either() -> None:
    with pytest.raises(UnitEconomicsError):
        RideCost(judged_windows=0, ranked_windows=-1)


def test_a_ride_with_no_judging_or_ranking_still_carries_its_storage_cost() -> None:
    cost = RideCost(judged_windows=0, ranked_windows=0)
    assert cost.judge_jpy == 0.0
    assert cost.rank_jpy == 0.0
    assert cost.total_jpy == pytest.approx(ESTIMATED_STORAGE_JPY_PER_RIDE)


def test_spend_exactly_at_a_tiers_ceiling_still_fits_it() -> None:
    """`fits` is `<=`: a ride that spends every last yen the tier allows still fits."""
    tier = PriceTier("t", 100.0, rides_per_month=1, gross_margin=0.0)
    cost = RideCost(judged_windows=0, ranked_windows=0, storage_jpy=tier.ceiling_jpy_per_ride)

    assert cost.total_jpy == pytest.approx(tier.ceiling_jpy_per_ride)
    assert cost.fits(tier)


def test_a_yen_over_a_tiers_ceiling_does_not_fit_it() -> None:
    tier = PriceTier("t", 100.0, rides_per_month=1, gross_margin=0.0)
    cost = RideCost(judged_windows=0, ranked_windows=0, storage_jpy=tier.ceiling_jpy_per_ride + 1.0)

    assert not cost.fits(tier)


def test_cheapest_fitting_tier_is_the_cheapest_by_price_not_by_declaration_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk the actual tier list rather than assume TIERS is already sorted."""
    reversed_tiers = tuple(sorted(TIERS, key=lambda t: t.monthly_jpy, reverse=True))
    assert reversed_tiers[0].monthly_jpy > reversed_tiers[-1].monthly_jpy
    monkeypatch.setattr("app.unit_economics.TIERS", reversed_tiers)

    cost = ranking_only_pipeline(1)  # trivially cheap: fits every declared tier

    assert cost.fits(TIER_100)
    assert cost.fits(TIER_300)
    assert cheapest_fitting_tier(cost) is TIER_100


def test_current_pipeline_never_ranks_more_windows_than_it_judged() -> None:
    """Fewer candidates than the default 40 to rank caps ranked_windows, not judged_windows."""
    cost = current_pipeline(10)

    assert cost.judged_windows == 10
    assert cost.ranked_windows == 10


def test_current_pipeline_honours_an_explicit_ranked_windows_below_the_candidate_count() -> None:
    cost = current_pipeline(10, ranked_windows=5)

    assert cost.judged_windows == 10
    assert cost.ranked_windows == 5


def test_ranking_only_pipeline_inflates_by_the_documented_fifteen_percent() -> None:
    cost = ranking_only_pipeline(10)

    assert cost.judged_windows == 0
    assert cost.ranked_windows == round(10 * 1.15)
