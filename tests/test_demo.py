"""Boundary and failure-path tests for the synthetic-only demo data in app.demo.

app.demo builds every fixture from hardcoded, non-private constants: it never
reads a package, a track, or a filename. These tests check the shapes and
failure paths that the indirect uses in other test files (test_director.py,
test_video_catalog.py, test_story_agent_localization.py, ...) do not exercise
directly.
"""

from __future__ import annotations

import pytest

from app.agents import StoryOutputLanguage
from app.contracts import DecisionStatus
from app.demo import (
    DEMO_STEPS,
    SCENARIO_LABELS,
    build_demo_candidate_edit_plan,
    build_demo_event,
    build_demo_story_inputs,
    build_demo_story_plan,
    build_synthetic_director_events,
    run_demo,
)
from app.edit.candidate_planner import CandidateEvidenceStatus, CandidatePlanStatus


def test_build_demo_event_is_a_single_fixed_window() -> None:
    event = build_demo_event()

    assert event.event_id == "evt_sample_001"
    assert event.start_time < event.end_time
    assert event.video_query.clip_start_offset_s < event.video_query.clip_end_offset_s


@pytest.mark.parametrize("scenario", sorted(SCENARIO_LABELS[StoryOutputLanguage.JAPANESE]))
def test_run_demo_accepts_every_documented_scenario(scenario: str) -> None:
    result = run_demo(scenario)

    assert result.scenario == scenario
    assert result.label == SCENARIO_LABELS[StoryOutputLanguage.JAPANESE][scenario]
    assert result.steps == DEMO_STEPS[StoryOutputLanguage.JAPANESE]


def test_run_demo_rejects_an_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="unknown demo scenario"):
        run_demo("not_a_real_scenario")


def test_run_demo_accepts_a_plain_string_language_like_a_web_query_param() -> None:
    # The web layer passes a raw query string through; StoryOutputLanguage(...)
    # must coerce it rather than require the caller to construct the enum.
    result = run_demo("accepted", "en")  # type: ignore[arg-type]

    assert result.label == SCENARIO_LABELS[StoryOutputLanguage.ENGLISH]["accepted"]


def test_run_demo_rejects_an_unknown_language() -> None:
    with pytest.raises(ValueError):
        run_demo("accepted", "de")  # type: ignore[arg-type]


def test_run_demo_accepted_confirms_the_video_evidence() -> None:
    result = run_demo("accepted")

    assert result.decision.decision_status is DecisionStatus.ACCEPTED
    assert result.decision.needs_video_evidence is True
    assert result.decision.updated_story_role is not None


def test_run_demo_rejected_is_not_accepted_but_still_resolved() -> None:
    result = run_demo("rejected")

    assert result.decision.decision_status is DecisionStatus.REJECTED
    assert result.decision.needs_video_evidence is True


def test_run_demo_missing_asset_fails_safe_to_human_review() -> None:
    # No matching media at all is not a rejection of the footage; it is an
    # unanswered question, so the decision must not silently resolve either
    # way.
    result = run_demo("missing_asset")

    assert result.decision.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW


def test_run_demo_gemini_unavailable_fails_safe_to_human_review() -> None:
    # The synthetic transport raises ConnectionError; the orchestrator must
    # not let that surface as an uncaught exception or as a silent accept.
    result = run_demo("gemini_unavailable")

    assert result.decision.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW


def test_demo_story_inputs_bracket_the_sample_event_in_time() -> None:
    summary, events = build_demo_story_inputs()

    departure, middle, arrival = events
    assert departure.event_type == "departure"
    assert arrival.event_type == "arrival_candidate"
    assert departure.start_time <= middle.start_time <= arrival.start_time
    assert summary.start_time == departure.start_time
    assert summary.end_time == arrival.end_time


@pytest.mark.parametrize("language", list(StoryOutputLanguage))
def test_build_demo_story_plan_produces_at_least_one_chapter(
    language: StoryOutputLanguage,
) -> None:
    plan = build_demo_story_plan(language)

    assert len(plan.chapters) >= 1


def test_synthetic_director_events_carry_no_coordinates_or_real_identifiers() -> None:
    events = build_synthetic_director_events()

    assert len(events) == 4
    assert [e.event_type for e in events] == [
        "departure",
        "direction_change",
        "scenery_change",
        "arrival_candidate",
    ]
    for event in events:
        assert event.source_asset_id.startswith("synthetic-director-")
        assert event.evidence_confirmed is True
        assert event.location_context.place_name is None


def test_synthetic_director_events_are_ordered_and_non_overlapping() -> None:
    events = build_synthetic_director_events()

    for earlier, later in zip(events, events[1:]):
        assert earlier.requested_end_sec <= later.requested_start_sec


def test_synthetic_director_arc_rises_to_a_climax_then_resolves() -> None:
    # The docstring promises a synthetic journey arc; the intensity/ranking
    # should actually climb toward "synthetic_climax" and fall away after it.
    events = {e.event_id: e for e in build_synthetic_director_events()}

    assert events["synthetic_departure"].intensity < events["synthetic_climax"].intensity
    assert events["synthetic_arrival"].intensity < events["synthetic_climax"].intensity


def test_demo_candidate_edit_plan_is_deliberately_incomplete() -> None:
    # The docstring says this is deliberately incomplete; assert what that
    # means concretely so a future edit that accidentally makes it complete
    # (and stops exercising the "not ready" web/CLI path) is caught.
    plan, review = build_demo_candidate_edit_plan()

    assert plan.status is CandidatePlanStatus.NEEDS_MORE_EVIDENCE
    assert review.is_ready_for_edit is False
    assert review.missing_duration_s > 0
    assert any(
        clip.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
        for clip in plan.clips
    )


def test_demo_candidate_edit_plan_reasons_do_not_repeat_event_ids() -> None:
    # Reasons are meant to be printable summaries, not object dumps; the
    # event ids belong only in the dedicated id tuples.
    _plan, review = build_demo_candidate_edit_plan()

    for reason in review.reasons:
        for event_id in review.event_ids_requiring_evidence:
            assert event_id not in reason
