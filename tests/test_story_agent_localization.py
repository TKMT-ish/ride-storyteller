import pytest

from app.agents import RuleBasedStoryAgent, StoryOutputLanguage
from app.demo import run_demo


@pytest.mark.parametrize(
    "scenario",
    ("accepted", "rejected", "missing_asset", "gemini_unavailable"),
)
def test_demo_language_changes_text_without_changing_decision_structure(
    scenario: str,
) -> None:
    japanese = run_demo(scenario, StoryOutputLanguage.JAPANESE)
    english = run_demo(scenario, StoryOutputLanguage.ENGLISH)

    assert english.scenario == japanese.scenario
    assert english.decision.event_id == japanese.decision.event_id
    assert english.decision.needs_video_evidence == japanese.decision.needs_video_evidence
    assert english.decision.asset_name_hint == japanese.decision.asset_name_hint
    assert english.decision.decision_status is japanese.decision.decision_status
    assert english.decision.reason != japanese.decision.reason
    assert english.label != japanese.label
    assert english.steps != japanese.steps


def test_english_agent_generates_english_story_role_after_acceptance() -> None:
    result = run_demo("accepted", StoryOutputLanguage.ENGLISH)

    assert result.decision.reason == (
        "The video analysis supports this GPS event's importance to the story."
    )
    assert result.decision.updated_story_role == ("Use this as a turning point in the journey.")


def test_story_agent_rejects_unknown_output_language() -> None:
    with pytest.raises(ValueError):
        RuleBasedStoryAgent("de")  # type: ignore[arg-type]
