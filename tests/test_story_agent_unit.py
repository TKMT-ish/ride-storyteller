"""Direct unit tests for RuleBasedStoryAgent's three decision methods.

`tests/test_story_agent.py` and `tests/test_story_agent_localization.py`
only exercise this agent indirectly, through `PrototypeOrchestrator` and
`app.demo.run_demo`. Neither pins the boundary values the agent's own
`>= 0.60` comparisons hinge on, nor `needs_human_review`'s two failure
reasons directly, nor the privacy invariant this codebase holds every
module to: a rejection/awaiting reason must not repeat the event id it
is about. This file calls `RuleBasedStoryAgent` directly with synthetic
fixtures built in-process -- no path, asset id, coordinate, or timestamp
here is real, and none is asserted to appear in any decision text.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents import RuleBasedStoryAgent, StoryEvidenceFailure, StoryOutputLanguage
from app.contracts import (
    DecisionStatus,
    GpsEvent,
    Location,
    StoryDecision,
    VideoAnalysis,
    VideoQuery,
)


def _event(
    *,
    event_id: str = "evt-1",
    event_type: str = "scenery_change",
    importance_hint: float = 0.72,
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC),
        location=Location(latitude=0.0, longitude=0.0),
        importance_hint=importance_hint,
        evidence=(),
        video_query=VideoQuery("asset-hint.mp4"),
    )


def _analysis(*, story_relevance_score: float) -> VideoAnalysis:
    return VideoAnalysis(
        "asset-hint.mp4",
        0,
        30,
        "synthetic clip",
        "unknown",
        (),
        "unknown",
        0.5,
        story_relevance_score,
        0.9,
        "synthetic",
    )


def _awaiting_decision(agent: RuleBasedStoryAgent, event_id: str = "evt-1") -> StoryDecision:
    return agent.decide_from_event(_event(event_id=event_id))


# -- decide_from_event: the 0.60 importance boundary and event_type gate --


def test_importance_hint_exactly_at_the_threshold_needs_evidence() -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(_event(importance_hint=0.60))
    assert decision.needs_video_evidence is True
    assert decision.decision_status is DecisionStatus.AWAITING_VIDEO_EVIDENCE


def test_importance_hint_just_under_the_threshold_is_rejected_without_evidence() -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(_event(importance_hint=0.599999))
    assert decision.needs_video_evidence is False
    assert decision.decision_status is DecisionStatus.REJECTED
    assert decision.asset_name_hint is None


def test_a_high_importance_event_outside_the_evidence_types_is_still_rejected() -> None:
    # event_type gates the same as importance_hint does: both must hold.
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(_event(event_type="normal_ride", importance_hint=0.99))
    assert decision.needs_video_evidence is False
    assert decision.decision_status is DecisionStatus.REJECTED


@pytest.mark.parametrize("event_type", ("scenery_change", "arrival_candidate", "elevation_change"))
def test_each_named_evidence_event_type_awaits_evidence_at_the_threshold(
    event_type: str,
) -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(_event(event_type=event_type, importance_hint=0.60))
    assert decision.decision_status is DecisionStatus.AWAITING_VIDEO_EVIDENCE


def test_awaiting_decision_carries_the_events_own_asset_hint_and_id() -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.decide_from_event(_event(event_id="evt-carry"))
    assert decision.event_id == "evt-carry"
    assert decision.asset_name_hint == "asset-hint.mp4"


# -- update_with_video: the 0.60 relevance boundary --


def test_story_relevance_exactly_at_the_threshold_is_accepted() -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.update_with_video(
        _awaiting_decision(agent), _analysis(story_relevance_score=0.60)
    )
    assert decision.decision_status is DecisionStatus.ACCEPTED
    assert decision.updated_story_role is not None


def test_story_relevance_just_under_the_threshold_is_rejected() -> None:
    agent = RuleBasedStoryAgent()
    decision = agent.update_with_video(
        _awaiting_decision(agent), _analysis(story_relevance_score=0.599999)
    )
    assert decision.decision_status is DecisionStatus.REJECTED
    assert decision.updated_story_role is None


def test_rejection_after_video_evidence_still_reports_needs_video_evidence_true() -> None:
    # This looks contradictory (rejected, yet needs_video_evidence=True) but
    # matches the field's meaning here: evidence *was* sought and used, the
    # story just wasn't confirmed by it. Pin the value so a future "tidy up"
    # doesn't flip it and silently change what downstream code sees.
    agent = RuleBasedStoryAgent()
    decision = agent.update_with_video(
        _awaiting_decision(agent), _analysis(story_relevance_score=0.0)
    )
    assert decision.needs_video_evidence is True


def test_accepted_decision_keeps_the_asset_hint_the_awaiting_decision_had() -> None:
    agent = RuleBasedStoryAgent()
    awaiting = agent.decide_from_event(_event(event_id="evt-2"))
    accepted = agent.update_with_video(awaiting, _analysis(story_relevance_score=1.0))
    assert accepted.event_id == "evt-2"
    assert accepted.asset_name_hint == awaiting.asset_name_hint


# -- needs_human_review: both failure reasons, both languages --


@pytest.mark.parametrize(
    "failure", (StoryEvidenceFailure.MISSING_ASSET, StoryEvidenceFailure.ANALYSIS_UNAVAILABLE)
)
@pytest.mark.parametrize("language", (StoryOutputLanguage.JAPANESE, StoryOutputLanguage.ENGLISH))
def test_needs_human_review_always_sets_that_decision_status(
    failure: StoryEvidenceFailure, language: StoryOutputLanguage
) -> None:
    agent = RuleBasedStoryAgent(language)
    decision = agent.needs_human_review(_event(), failure)
    assert decision.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    assert decision.needs_video_evidence is True


def test_needs_human_review_accepts_a_raw_string_the_same_as_the_enum() -> None:
    # `app.demo` calls this from a web-layer query-string style string, not
    # necessarily the enum member -- StoryEvidenceFailure(failure) must
    # coerce it the same way StoryOutputLanguage does elsewhere in the app.
    agent = RuleBasedStoryAgent()
    from_enum = agent.needs_human_review(_event(), StoryEvidenceFailure.MISSING_ASSET)
    from_string = agent.needs_human_review(_event(), "missing_asset")
    assert from_enum.reason == from_string.reason


def test_needs_human_review_rejects_an_unknown_failure_reason() -> None:
    agent = RuleBasedStoryAgent()
    with pytest.raises(ValueError):
        agent.needs_human_review(_event(), "camera_exploded")


def test_missing_asset_and_analysis_unavailable_give_different_reasons() -> None:
    agent = RuleBasedStoryAgent()
    missing = agent.needs_human_review(_event(), StoryEvidenceFailure.MISSING_ASSET)
    unavailable = agent.needs_human_review(_event(), StoryEvidenceFailure.ANALYSIS_UNAVAILABLE)
    assert missing.reason != unavailable.reason


# -- privacy invariant shared across app.tenancy / app.retention / app.demo --


@pytest.mark.parametrize(
    "make_decision",
    (
        lambda agent, event: agent.decide_from_event(event),
        lambda agent, event: agent.update_with_video(
            agent.decide_from_event(event), _analysis(story_relevance_score=0.0)
        ),
        lambda agent, event: agent.update_with_video(
            agent.decide_from_event(event), _analysis(story_relevance_score=1.0)
        ),
        lambda agent, event: agent.needs_human_review(event, StoryEvidenceFailure.MISSING_ASSET),
        lambda agent, event: agent.needs_human_review(
            event, StoryEvidenceFailure.ANALYSIS_UNAVAILABLE
        ),
    ),
)
@pytest.mark.parametrize("language", (StoryOutputLanguage.JAPANESE, StoryOutputLanguage.ENGLISH))
def test_reason_text_never_repeats_the_events_own_id(
    make_decision, language: StoryOutputLanguage
) -> None:
    distinctive_event_id = "evt-do-not-echo-me-back-8271"
    agent = RuleBasedStoryAgent(language)
    decision = make_decision(agent, _event(event_id=distinctive_event_id, importance_hint=0.99))
    assert distinctive_event_id not in decision.reason
