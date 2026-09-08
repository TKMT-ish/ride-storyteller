"""What a ride costs to make, against what a subscription can afford.

Ride Storyteller is to be sold at 100 to 300 yen a month. Whether that
works is decided by one number: the model spend per ride. Everything else
-- hosting, storage, payment fees -- is small beside it. So the figure is
computed here from measured rates, not from the price list, and shown next
to every plan so nobody has to do the arithmetic.

The rates were measured on real rides on 2026-09-03 and 2026-09-04:
judging one twelve-second window cost 0.148 yen (173 windows, 25.56 yen);
ranking one window in a group of ten cost 0.056 yen (40 windows, 2.25 yen).
Estimates below are linear in those rates and say so. When a pipeline
changes, measure again and change the constant, with the date.

A tier's ceiling is what a month's price leaves for the model after the
gross margin, divided by the rides a subscriber is assumed to make. Four
rides a month at 100 yen and a 70% margin leaves 7.5 yen a ride.
"""

from __future__ import annotations

from dataclasses import dataclass

UNIT_ECONOMICS_SCHEMA_VERSION = "unit-economics-v1"

# Measured 2026-09-03/04 on Gemini 2.5 Flash, 12 s windows, 480p, 1 fps, no audio.
MEASURED_JUDGE_JPY_PER_WINDOW = 0.148
MEASURED_RANK_JPY_PER_WINDOW = 0.056
# 95 MB of copies kept thirty days at Tokyo prices; egress to Vertex in-region is nil.
ESTIMATED_STORAGE_JPY_PER_RIDE = 0.4

DEFAULT_GROSS_MARGIN = 0.70
DEFAULT_RIDES_PER_MONTH = 4


class UnitEconomicsError(ValueError):
    """Raised when a cost or a tier cannot be described as asked."""


@dataclass(frozen=True)
class PriceTier:
    """A monthly price, and what it leaves for the model per ride."""

    name: str
    monthly_jpy: float
    rides_per_month: int = DEFAULT_RIDES_PER_MONTH
    gross_margin: float = DEFAULT_GROSS_MARGIN

    def __post_init__(self) -> None:
        if self.monthly_jpy <= 0 or self.rides_per_month < 1:
            raise UnitEconomicsError("a tier needs a positive price and at least one ride")
        if not 0.0 <= self.gross_margin < 1.0:
            raise UnitEconomicsError("a gross margin is a fraction below one")

    @property
    def ceiling_jpy_per_ride(self) -> float:
        return self.monthly_jpy * (1.0 - self.gross_margin) / self.rides_per_month


TIER_100 = PriceTier("tier-100", 100.0)
TIER_300 = PriceTier("tier-300", 300.0)
TIERS: tuple[PriceTier, ...] = (TIER_100, TIER_300)


@dataclass(frozen=True)
class RideCost:
    """The model spend one ride would take, by stage, in yen."""

    judged_windows: int
    ranked_windows: int
    judge_jpy_per_window: float = MEASURED_JUDGE_JPY_PER_WINDOW
    rank_jpy_per_window: float = MEASURED_RANK_JPY_PER_WINDOW
    storage_jpy: float = ESTIMATED_STORAGE_JPY_PER_RIDE

    def __post_init__(self) -> None:
        if self.judged_windows < 0 or self.ranked_windows < 0:
            raise UnitEconomicsError("a ride cannot have negative windows")

    @property
    def judge_jpy(self) -> float:
        return self.judged_windows * self.judge_jpy_per_window

    @property
    def rank_jpy(self) -> float:
        return self.ranked_windows * self.rank_jpy_per_window

    @property
    def total_jpy(self) -> float:
        return self.judge_jpy + self.rank_jpy + self.storage_jpy

    def fits(self, tier: PriceTier) -> bool:
        return self.total_jpy <= tier.ceiling_jpy_per_ride

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": UNIT_ECONOMICS_SCHEMA_VERSION,
            "judged_windows": self.judged_windows,
            "ranked_windows": self.ranked_windows,
            "judge_jpy": round(self.judge_jpy, 2),
            "rank_jpy": round(self.rank_jpy, 2),
            "storage_jpy": round(self.storage_jpy, 2),
            "total_jpy": round(self.total_jpy, 2),
            "tiers": {
                tier.name: {
                    "ceiling_jpy_per_ride": round(tier.ceiling_jpy_per_ride, 2),
                    "fits": self.fits(tier),
                }
                for tier in TIERS
            },
        }


def current_pipeline(candidate_count: int, *, ranked_windows: int = 40) -> RideCost:
    """Judge every window, then rank the forty around the cut: what runs today."""
    return RideCost(
        judged_windows=candidate_count, ranked_windows=min(ranked_windows, candidate_count)
    )


def ranking_only_pipeline(candidate_count: int) -> RideCost:
    """Rank every window in groups of ten with a final: the cheaper path Gate 7 aims at.

    The final adds about fifteen percent -- the winners of each group are
    compared once more -- so the ranked count is inflated by that much.
    """
    return RideCost(judged_windows=0, ranked_windows=round(candidate_count * 1.15))


def cheapest_fitting_tier(cost: RideCost) -> PriceTier | None:
    """The lowest tier this ride's spend fits inside, or None if none does."""
    for tier in sorted(TIERS, key=lambda t: t.monthly_jpy):
        if cost.fits(tier):
            return tier
    return None
