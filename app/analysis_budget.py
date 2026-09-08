"""Decide what Gemini may look at, before any of it is paid for.

Judging real footage costs money per second of video, and a ride produces far
more candidate footage than a film needs. So the selection runs as a cascade:
cheap stages look at everything and pass on a fraction, expensive stages look
only at what survived. Each stage costs more per candidate than the one before
and sees fewer of them.

The budget is enforced by estimating, never by watching the bill. A plan is
produced first, its cost is compared against the ceiling, and if it does not
fit the cascade is tightened -- fewer candidates reach the expensive stages --
until it does. If even the cheapest stage cannot fit, nothing is sent at all:
a partial spend that answers nothing is worse than not starting.

Token rates come from Google's published media tokenisation: roughly 66 tokens
for a low-resolution frame and 258 for a high-resolution one, and video at
about 100 tokens per second at low media resolution or 300 at high. Prices and
the exchange rate are inputs, not constants, because both move and a stale
number here would silently misreport what a run costs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

ANALYSIS_BUDGET_SCHEMA_VERSION = "analysis-budget-v1"

# Google's published media tokenisation, used to size a request before making
# it. Confirm against current documentation before trusting a large estimate.
TOKENS_PER_LOW_RESOLUTION_FRAME = 66
TOKENS_PER_HIGH_RESOLUTION_FRAME = 258
TOKENS_PER_SECOND_LOW_RESOLUTION = 100
TOKENS_PER_SECOND_HIGH_RESOLUTION = 300

# Gemini 2.5 Flash list price at the time of writing. Passed in rather than
# assumed anywhere that matters.
DEFAULT_INPUT_USD_PER_MILLION_TOKENS = 0.30
DEFAULT_OUTPUT_USD_PER_MILLION_TOKENS = 2.50

# One structured VideoAnalysis response: seven short fields.
DEFAULT_OUTPUT_TOKENS_PER_CANDIDATE = 250

# A screening verdict: a score and a keep-or-drop, nothing else.
#
# This size is the whole reason an extra stage can save money. Output is
# charged at roughly eight times input here, so a screening stage returning a
# full analysis pays the dominant cost for every candidate it screens and
# saves only the cheaper half. Measured on one real ride, adding such a stage
# made the run *more* expensive. A screening stage must be cheap on both
# sides or it is not a saving, it is an extra bill.
SCREENING_OUTPUT_TOKENS_PER_CANDIDATE = 12

# An assumption, and marked as one. A wrong rate misreports every estimate.
DEFAULT_JPY_PER_USD = 150.0


class AnalysisBudgetError(ValueError):
    """Raised when no cascade can be run within the money allowed."""


@dataclass(frozen=True)
class AnalysisStage:
    """One pass over the candidates, and what it costs to look at each."""

    name: str
    input_tokens_per_candidate: int
    keep_ratio: float
    output_tokens_per_candidate: int = DEFAULT_OUTPUT_TOKENS_PER_CANDIDATE

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("an analysis stage needs a name")
        if self.input_tokens_per_candidate < 0 or self.output_tokens_per_candidate < 0:
            raise ValueError("an analysis stage cannot cost negative tokens")
        if not 0.0 < self.keep_ratio <= 1.0:
            raise ValueError("a stage must keep some candidates and cannot keep more than all")

    @property
    def is_free(self) -> bool:
        """A local stage costs no tokens; it still narrows the field."""
        return self.input_tokens_per_candidate == 0 and self.output_tokens_per_candidate == 0


@dataclass(frozen=True)
class StageEstimate:
    """What one stage would see, and what looking would cost."""

    name: str
    candidates_in: int
    candidates_out: int
    input_tokens: int
    output_tokens: int
    usd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "candidates_in": self.candidates_in,
            "candidates_out": self.candidates_out,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
        }


@dataclass(frozen=True)
class CascadePlan:
    """A cascade that fits the money allowed, and what it had to give up."""

    stages: tuple[StageEstimate, ...]
    budget_jpy: float
    jpy_per_usd: float
    tightened: bool

    @property
    def total_usd(self) -> float:
        return sum(stage.usd for stage in self.stages)

    @property
    def total_jpy(self) -> float:
        return self.total_usd * self.jpy_per_usd

    @property
    def final_candidate_count(self) -> int:
        return self.stages[-1].candidates_out if self.stages else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": ANALYSIS_BUDGET_SCHEMA_VERSION,
            "budget_jpy": round(self.budget_jpy, 2),
            "jpy_per_usd": self.jpy_per_usd,
            "total_usd": round(self.total_usd, 6),
            "total_jpy": round(self.total_jpy, 2),
            "within_budget": self.total_jpy <= self.budget_jpy,
            "tightened_to_fit": self.tightened,
            "final_candidate_count": self.final_candidate_count,
            "stages": [stage.to_dict() for stage in self.stages],
        }


def video_stage(
    name: str,
    *,
    seconds_per_candidate: float,
    keep_ratio: float,
    high_resolution: bool = False,
) -> AnalysisStage:
    """A stage that watches each candidate clip."""
    if seconds_per_candidate <= 0:
        raise AnalysisBudgetError("a video stage needs a positive clip length")
    rate = (
        TOKENS_PER_SECOND_HIGH_RESOLUTION if high_resolution else TOKENS_PER_SECOND_LOW_RESOLUTION
    )
    return AnalysisStage(
        name=name,
        input_tokens_per_candidate=round(seconds_per_candidate * rate),
        keep_ratio=keep_ratio,
    )


def stills_stage(
    name: str,
    *,
    frames_per_candidate: int,
    keep_ratio: float,
    high_resolution: bool = False,
    screening: bool = True,
) -> AnalysisStage:
    """A stage that looks at a few frames instead of watching the clip.

    `screening=True` (the default) asks for only a score and a verdict, which
    is what makes an extra stage cheaper rather than dearer -- see
    `SCREENING_OUTPUT_TOKENS_PER_CANDIDATE`. Pass `screening=False` when the
    stage's full answer is wanted and the saving is not the point.
    """
    if frames_per_candidate <= 0:
        raise AnalysisBudgetError("a stills stage needs at least one frame")
    rate = TOKENS_PER_HIGH_RESOLUTION_FRAME if high_resolution else TOKENS_PER_LOW_RESOLUTION_FRAME
    return AnalysisStage(
        name=name,
        input_tokens_per_candidate=frames_per_candidate * rate,
        keep_ratio=keep_ratio,
        output_tokens_per_candidate=(
            SCREENING_OUTPUT_TOKENS_PER_CANDIDATE
            if screening
            else DEFAULT_OUTPUT_TOKENS_PER_CANDIDATE
        ),
    )


def local_stage(name: str, *, keep_ratio: float) -> AnalysisStage:
    """A stage run on this machine. It costs nothing and still narrows."""
    return AnalysisStage(
        name=name,
        input_tokens_per_candidate=0,
        keep_ratio=keep_ratio,
        output_tokens_per_candidate=0,
    )


def estimate_cascade(
    candidate_count: int,
    stages: tuple[AnalysisStage, ...],
    *,
    input_usd_per_million: float = DEFAULT_INPUT_USD_PER_MILLION_TOKENS,
    output_usd_per_million: float = DEFAULT_OUTPUT_USD_PER_MILLION_TOKENS,
) -> tuple[StageEstimate, ...]:
    """Cost every stage against the number of candidates that reach it."""
    if candidate_count < 0:
        raise AnalysisBudgetError("a cascade cannot start with negative candidates")
    if not stages:
        raise AnalysisBudgetError("a cascade needs at least one stage")

    estimates: list[StageEstimate] = []
    remaining = candidate_count
    for stage in stages:
        input_tokens = remaining * stage.input_tokens_per_candidate
        output_tokens = remaining * stage.output_tokens_per_candidate
        usd = (
            input_tokens * input_usd_per_million + output_tokens * output_usd_per_million
        ) / 1_000_000
        surviving = max(1, round(remaining * stage.keep_ratio)) if remaining else 0
        estimates.append(
            StageEstimate(
                name=stage.name,
                candidates_in=remaining,
                candidates_out=surviving,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usd=usd,
            )
        )
        remaining = surviving
    return tuple(estimates)


def plan_cascade_within_budget(
    candidate_count: int,
    stages: tuple[AnalysisStage, ...],
    *,
    budget_jpy: float,
    jpy_per_usd: float = DEFAULT_JPY_PER_USD,
    input_usd_per_million: float = DEFAULT_INPUT_USD_PER_MILLION_TOKENS,
    output_usd_per_million: float = DEFAULT_OUTPUT_USD_PER_MILLION_TOKENS,
    minimum_keep_ratio: float = 0.02,
) -> CascadePlan:
    """Fit the cascade inside the money allowed, tightening it if it must.

    Tightening means letting fewer candidates through, and it is applied to
    the stage *before* an expensive one rather than to the expensive stage
    itself. A stage's own cost is set by how many candidates reach it, so
    narrowing its keep ratio changes only what comes after; the lever that
    lowers a costly stage's bill is its feeder. Free local stages are the best
    feeders to tighten, since narrowing them costs nothing and throttles
    everything downstream.

    The last stage's keep ratio is never touched: nothing follows it, so
    tightening it would give up results without saving a yen.

    A cascade that cannot fit even at its tightest is refused rather than
    started. Spending part of a budget on an answer nobody will use is worse
    than spending none.
    """
    if budget_jpy <= 0:
        raise AnalysisBudgetError("a cascade needs a positive budget")
    if jpy_per_usd <= 0:
        raise AnalysisBudgetError("the exchange rate must be positive")
    if not 0.0 < minimum_keep_ratio <= 1.0:
        raise AnalysisBudgetError("the minimum keep ratio must be a fraction of all")

    def cost(current: tuple[AnalysisStage, ...]) -> tuple[StageEstimate, ...]:
        return estimate_cascade(
            candidate_count,
            current,
            input_usd_per_million=input_usd_per_million,
            output_usd_per_million=output_usd_per_million,
        )

    current = stages
    estimates = cost(current)
    if sum(stage.usd for stage in estimates) * jpy_per_usd <= budget_jpy:
        return CascadePlan(
            stages=estimates,
            budget_jpy=budget_jpy,
            jpy_per_usd=jpy_per_usd,
            tightened=False,
        )

    # Walk the feeders from the latest backwards. Index len-1 is skipped:
    # nothing follows the last stage, so its keep ratio costs nothing.
    for index in range(len(current) - 2, -1, -1):
        while current[index].keep_ratio > minimum_keep_ratio:
            current = (
                current[:index]
                + (
                    replace(
                        current[index],
                        keep_ratio=max(minimum_keep_ratio, current[index].keep_ratio / 2),
                    ),
                )
                + current[index + 1 :]
            )
            estimates = cost(current)
            if sum(item.usd for item in estimates) * jpy_per_usd <= budget_jpy:
                return CascadePlan(
                    stages=estimates,
                    budget_jpy=budget_jpy,
                    jpy_per_usd=jpy_per_usd,
                    tightened=True,
                )

    raise AnalysisBudgetError(
        "no cascade fits this budget; raise it, shorten the clips, "
        "or narrow the candidates before analysis"
    )
