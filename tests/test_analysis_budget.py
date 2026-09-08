"""Synthetic-fixture tests for costing the analysis cascade before spending."""

from __future__ import annotations

import pytest

from app.analysis_budget import (
    ANALYSIS_BUDGET_SCHEMA_VERSION,
    DEFAULT_INPUT_USD_PER_MILLION_TOKENS,
    DEFAULT_OUTPUT_TOKENS_PER_CANDIDATE,
    SCREENING_OUTPUT_TOKENS_PER_CANDIDATE,
    TOKENS_PER_LOW_RESOLUTION_FRAME,
    TOKENS_PER_SECOND_HIGH_RESOLUTION,
    TOKENS_PER_SECOND_LOW_RESOLUTION,
    AnalysisBudgetError,
    AnalysisStage,
    estimate_cascade,
    local_stage,
    plan_cascade_within_budget,
    stills_stage,
    video_stage,
)


def _cascade() -> tuple[AnalysisStage, ...]:
    """Free local narrowing, then stills, then video on the survivors."""
    return (
        local_stage("local-metrics", keep_ratio=0.5),
        stills_stage("gemini-stills", frames_per_candidate=3, keep_ratio=0.3),
        video_stage("gemini-video", seconds_per_candidate=12.0, keep_ratio=0.35),
    )


# --- what a stage costs -----------------------------------------------------


def test_a_local_stage_costs_nothing_and_still_narrows() -> None:
    stage = local_stage("local", keep_ratio=0.1)

    assert stage.is_free
    estimates = estimate_cascade(100, (stage,))
    assert estimates[0].usd == 0.0
    assert estimates[0].candidates_out == 10


def test_stills_cost_less_than_watching_the_clip() -> None:
    stills = stills_stage("stills", frames_per_candidate=3, keep_ratio=0.5)
    video = video_stage("video", seconds_per_candidate=12.0, keep_ratio=0.5)

    assert stills.input_tokens_per_candidate == 3 * TOKENS_PER_LOW_RESOLUTION_FRAME
    assert video.input_tokens_per_candidate == round(12.0 * TOKENS_PER_SECOND_LOW_RESOLUTION)
    assert stills.input_tokens_per_candidate < video.input_tokens_per_candidate


def test_high_resolution_video_costs_three_times_low() -> None:
    low = video_stage("low", seconds_per_candidate=12.0, keep_ratio=0.5)
    high = video_stage("high", seconds_per_candidate=12.0, keep_ratio=0.5, high_resolution=True)

    assert high.input_tokens_per_candidate == pytest.approx(
        low.input_tokens_per_candidate
        * TOKENS_PER_SECOND_HIGH_RESOLUTION
        / TOKENS_PER_SECOND_LOW_RESOLUTION
    )


def test_the_estimate_is_arithmetic_anyone_can_check() -> None:
    """200 candidates, 12 s each, low resolution, input only."""
    stage = video_stage("video", seconds_per_candidate=12.0, keep_ratio=1.0)

    estimate = estimate_cascade(
        200,
        (
            AnalysisStage(
                name=stage.name,
                input_tokens_per_candidate=stage.input_tokens_per_candidate,
                keep_ratio=1.0,
                output_tokens_per_candidate=0,
            ),
        ),
    )[0]

    assert estimate.input_tokens == 200 * 1_200
    assert estimate.usd == pytest.approx(240_000 * DEFAULT_INPUT_USD_PER_MILLION_TOKENS / 1_000_000)


# --- the cascade ------------------------------------------------------------


def test_each_stage_sees_only_what_the_last_one_passed() -> None:
    estimates = estimate_cascade(200, _cascade())

    assert [stage.candidates_in for stage in estimates] == [200, 100, 30]
    assert estimates[-1].candidates_out == 10


def test_an_expensive_stage_costs_less_than_it_would_alone() -> None:
    """That is the point of a cascade: the costly look sees fewer things."""
    cascaded = estimate_cascade(200, _cascade())[-1]
    alone = estimate_cascade(
        200, (video_stage("video", seconds_per_candidate=12.0, keep_ratio=0.35),)
    )[0]

    assert cascaded.usd < alone.usd


def test_a_cascade_needs_a_stage_and_a_sane_count() -> None:
    with pytest.raises(AnalysisBudgetError, match="at least one stage"):
        estimate_cascade(10, ())
    with pytest.raises(AnalysisBudgetError, match="negative candidates"):
        estimate_cascade(-1, _cascade())


# --- the budget -------------------------------------------------------------


def test_a_plan_with_no_stages_at_all_reports_zero_rather_than_failing() -> None:
    """`CascadePlan` is a plain record; nothing stops it being built with an
    empty stage tuple directly, and its derived properties should not choke
    on that -- they should just say nothing happened."""
    from app.analysis_budget import CascadePlan

    plan = CascadePlan(stages=(), budget_jpy=100.0, jpy_per_usd=150.0, tightened=False)

    assert plan.final_candidate_count == 0
    assert plan.total_usd == 0
    assert plan.total_jpy == 0.0
    assert plan.to_dict()["within_budget"] is True


def test_a_plan_that_already_fits_is_left_alone() -> None:
    plan = plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0)

    assert plan.tightened is False
    assert plan.total_jpy <= 500.0
    assert plan.to_dict()["within_budget"] is True
    assert plan.to_dict()["schema_version"] == ANALYSIS_BUDGET_SCHEMA_VERSION


def test_this_ride_costs_far_less_than_the_ceiling() -> None:
    """The real question that prompted this: 200 candidates against 500 yen."""
    plan = plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0)

    assert plan.total_jpy < 50.0


def test_a_cascade_that_does_not_fit_is_tightened_rather_than_run() -> None:
    """Fewer candidates reach the costly stage until the whole thing fits."""
    huge = 200_000

    plan = plan_cascade_within_budget(huge, _cascade(), budget_jpy=500.0)

    assert plan.tightened is True
    assert plan.total_jpy <= 500.0
    # Tightening happens by letting fewer through, not by skipping a stage.
    assert [stage.name for stage in plan.stages] == [
        "local-metrics",
        "gemini-stills",
        "gemini-video",
    ]


def test_tightening_throttles_what_reaches_the_costly_stage() -> None:
    """A stage's bill is set by its feeder, so that is what gets narrowed."""
    plan = plan_cascade_within_budget(200_000, _cascade(), budget_jpy=500.0)

    untouched = estimate_cascade(200_000, _cascade())
    assert plan.stages[-1].candidates_in < untouched[-1].candidates_in
    assert plan.stages[-2].candidates_in < untouched[-2].candidates_in


def test_the_last_stage_keep_ratio_is_never_spent_on() -> None:
    """Nothing follows it, so narrowing it would lose results and save nothing."""
    stages = _cascade()
    plan = plan_cascade_within_budget(200_000, stages, budget_jpy=500.0)

    final = plan.stages[-1]
    assert final.candidates_out == max(1, round(final.candidates_in * stages[-1].keep_ratio))


def test_a_budget_nothing_can_fit_is_refused_not_part_spent() -> None:
    """A partial spend that answers nothing is worse than not starting."""
    with pytest.raises(AnalysisBudgetError, match="no cascade fits"):
        plan_cascade_within_budget(1_000_000, _cascade(), budget_jpy=0.01)


def test_the_exchange_rate_is_an_input_not_a_constant() -> None:
    cheap = plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0, jpy_per_usd=100.0)
    dear = plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0, jpy_per_usd=200.0)

    assert dear.total_jpy == pytest.approx(cheap.total_jpy * 2)
    assert dear.total_usd == pytest.approx(cheap.total_usd)


def test_an_impossible_budget_or_rate_is_refused() -> None:
    with pytest.raises(AnalysisBudgetError, match="positive budget"):
        plan_cascade_within_budget(200, _cascade(), budget_jpy=0.0)
    with pytest.raises(AnalysisBudgetError, match="exchange rate"):
        plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0, jpy_per_usd=0.0)


def test_a_stage_must_keep_some_and_cannot_keep_more_than_all() -> None:
    for ratio in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="keep"):
            AnalysisStage(name="x", input_tokens_per_candidate=1, keep_ratio=ratio)


def test_a_stage_needs_a_name_and_non_negative_cost() -> None:
    with pytest.raises(ValueError, match="needs a name"):
        AnalysisStage(name="", input_tokens_per_candidate=1, keep_ratio=0.5)
    with pytest.raises(ValueError, match="negative tokens"):
        AnalysisStage(name="x", input_tokens_per_candidate=-1, keep_ratio=0.5)


def test_empty_stage_helpers_are_refused() -> None:
    with pytest.raises(AnalysisBudgetError, match="positive clip length"):
        video_stage("v", seconds_per_candidate=0.0, keep_ratio=0.5)
    with pytest.raises(AnalysisBudgetError, match="at least one frame"):
        stills_stage("s", frames_per_candidate=0, keep_ratio=0.5)


def test_the_report_carries_no_private_detail() -> None:
    import json

    payload = plan_cascade_within_budget(200, _cascade(), budget_jpy=500.0).to_dict()
    serialized = json.dumps(payload)

    assert "final_candidate_count" in payload
    for forbidden in ("/Users/", ".mp4", "evt_", "latitude"):
        assert forbidden not in serialized


def test_a_screening_stage_returns_a_verdict_not_an_analysis() -> None:
    """Output is charged at roughly eight times input, so a screening stage
    that returned the full answer would cost more than it saved."""
    screening = stills_stage("screen", frames_per_candidate=3, keep_ratio=0.3)
    full = stills_stage("full", frames_per_candidate=3, keep_ratio=0.3, screening=False)

    assert screening.output_tokens_per_candidate == SCREENING_OUTPUT_TOKENS_PER_CANDIDATE
    assert full.output_tokens_per_candidate == DEFAULT_OUTPUT_TOKENS_PER_CANDIDATE
    assert screening.output_tokens_per_candidate < full.output_tokens_per_candidate


def test_zero_candidates_costs_nothing_and_keeps_nothing() -> None:
    """Zero is a valid boundary, distinct from the negative count that is refused."""
    estimate = estimate_cascade(0, _cascade())

    assert [stage.candidates_in for stage in estimate] == [0, 0, 0]
    assert [stage.candidates_out for stage in estimate] == [0, 0, 0]
    assert all(stage.usd == 0.0 for stage in estimate)


def test_rounding_to_survivors_is_banker_rounding_not_always_up() -> None:
    """`round()` breaks an exact .5 toward the nearest even number, not always up.
    Fixed as a behaviour so a future switch to a different rounding rule is a
    deliberate decision, not a silent one."""
    to_two_and_a_half = estimate_cascade(10, (local_stage("l", keep_ratio=0.25),))[0]
    to_three_and_a_half = estimate_cascade(10, (local_stage("l", keep_ratio=0.35),))[0]

    assert to_two_and_a_half.candidates_out == 2  # 2.5 -> 2 (even)
    assert to_three_and_a_half.candidates_out == 4  # 3.5 -> 4 (even)


def test_a_tiny_keep_ratio_never_drops_the_last_survivor_to_zero() -> None:
    """Rounding down to zero would erase the stage; at least one always survives
    while candidates remain."""
    estimate = estimate_cascade(1, (local_stage("l", keep_ratio=0.01),))[0]

    assert estimate.candidates_out == 1


def test_keep_ratio_boundary_is_inclusive_of_all_but_not_beyond() -> None:
    AnalysisStage(name="x", input_tokens_per_candidate=1, keep_ratio=1.0)  # all: allowed
    AnalysisStage(name="x", input_tokens_per_candidate=1, keep_ratio=1e-9)  # nearly none: allowed
    with pytest.raises(ValueError, match="keep"):
        AnalysisStage(name="x", input_tokens_per_candidate=1, keep_ratio=1.0 + 1e-9)


def test_a_stage_also_rejects_negative_output_tokens() -> None:
    with pytest.raises(ValueError, match="negative tokens"):
        AnalysisStage(
            name="x", input_tokens_per_candidate=1, keep_ratio=0.5, output_tokens_per_candidate=-1
        )


def test_is_free_requires_both_sides_to_cost_nothing() -> None:
    only_output_costs = AnalysisStage(
        name="a", input_tokens_per_candidate=0, keep_ratio=0.5, output_tokens_per_candidate=5
    )
    only_input_costs = AnalysisStage(
        name="b", input_tokens_per_candidate=5, keep_ratio=0.5, output_tokens_per_candidate=0
    )

    assert only_output_costs.is_free is False
    assert only_input_costs.is_free is False


def test_video_and_stills_stages_refuse_negative_lengths_too() -> None:
    """Not just the zero already covered -- a negative length is nonsense as well."""
    with pytest.raises(AnalysisBudgetError, match="positive clip length"):
        video_stage("v", seconds_per_candidate=-1.0, keep_ratio=0.5)
    with pytest.raises(AnalysisBudgetError, match="at least one frame"):
        stills_stage("s", frames_per_candidate=-1, keep_ratio=0.5)


def test_minimum_keep_ratio_boundary_is_validated_like_any_other_fraction() -> None:
    stages = (
        local_stage("l", keep_ratio=0.5),
        video_stage("v", seconds_per_candidate=12.0, keep_ratio=0.5),
    )

    with pytest.raises(AnalysisBudgetError, match="minimum keep ratio"):
        plan_cascade_within_budget(200, stages, budget_jpy=500.0, minimum_keep_ratio=0.0)
    with pytest.raises(AnalysisBudgetError, match="minimum keep ratio"):
        plan_cascade_within_budget(200, stages, budget_jpy=500.0, minimum_keep_ratio=1.5)


def test_minimum_keep_ratio_of_one_forbids_any_tightening() -> None:
    """A minimum of 1.0 is a valid fraction, but it leaves no room below any
    stage's own ratio, so a cascade that needs tightening can never get it."""
    stages = (
        local_stage("l", keep_ratio=0.5),
        video_stage("v", seconds_per_candidate=12.0, keep_ratio=0.5),
    )

    with pytest.raises(AnalysisBudgetError, match="no cascade fits"):
        plan_cascade_within_budget(200_000, stages, budget_jpy=500.0, minimum_keep_ratio=1.0)


def test_a_single_stage_cascade_can_never_be_tightened() -> None:
    """The only stage is also the last stage, and the last stage's keep ratio
    is never spent -- so an over-budget single-stage cascade always refuses,
    no matter how low the minimum keep ratio is allowed to go."""
    stage = (video_stage("v", seconds_per_candidate=12.0, keep_ratio=1.0),)

    with pytest.raises(AnalysisBudgetError, match="no cascade fits"):
        plan_cascade_within_budget(1_000_000, stage, budget_jpy=0.01, minimum_keep_ratio=0.001)


def test_tightening_clamps_exactly_to_the_minimum_and_stops_there() -> None:
    """One halving of 0.5 lands below 0.4, so it is clamped to 0.4 exactly --
    not left at the halved value and not halved again once it reaches the
    floor (0.4 is not > 0.4, so the loop's own condition stops it there)."""
    stages = (
        local_stage("l", keep_ratio=0.5),
        video_stage("v", seconds_per_candidate=12.0, keep_ratio=0.5),
    )

    plan = plan_cascade_within_budget(2000, stages, budget_jpy=130.0, minimum_keep_ratio=0.4)

    assert plan.tightened is True
    feeder = plan.stages[0]
    assert feeder.candidates_out / feeder.candidates_in == pytest.approx(0.4)


def test_screening_makes_the_extra_stage_worth_adding() -> None:
    """The measured point: with a full-output screen the cascade costs more."""
    video_only = (video_stage("video", seconds_per_candidate=12.0, keep_ratio=0.3),)
    with_screen = (
        stills_stage("screen", frames_per_candidate=3, keep_ratio=0.35),
        video_stage("video", seconds_per_candidate=12.0, keep_ratio=0.3),
    )
    with_costly_screen = (
        stills_stage("screen", frames_per_candidate=3, keep_ratio=0.35, screening=False),
        video_stage("video", seconds_per_candidate=12.0, keep_ratio=0.3),
    )

    def total(stages):
        return sum(item.usd for item in estimate_cascade(202, stages))

    assert total(with_screen) < total(video_only)
    assert total(with_costly_screen) > total(video_only)
