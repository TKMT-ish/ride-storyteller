from app.agent_runtime import get_synthetic_ride_event
from app.deployable_agent import (
    build_synthetic_deployment_agent,
    get_synthetic_deployment_event,
)


def test_deployable_agent_is_isolated_and_synthetic_only() -> None:
    agent = build_synthetic_deployment_agent("gemini-2.5-flash")
    event = get_synthetic_deployment_event()

    assert agent.name == "ride_storyteller_evidence_agent"
    assert len(agent.tools) == 1
    assert event["contains_real_gpx"] is False
    assert event["contains_real_media"] is False


def test_the_requested_model_string_is_forwarded_unchanged() -> None:
    agent = build_synthetic_deployment_agent("gemini-2.5-pro")
    assert agent.model == "gemini-2.5-pro"


def test_instruction_forbids_requesting_real_material() -> None:
    agent = build_synthetic_deployment_agent("gemini-2.5-flash")
    instruction = str(agent.instruction)
    assert "real GPX" in instruction
    assert "credentials" in instruction


def test_synthetic_event_matches_the_agent_runtime_layer_shape() -> None:
    # app.deployable_agent exists only so Agent Runtime can deploy without
    # importing the rest of app.agent_runtime; its fixed event is meant to
    # be the same fact as app.agent_runtime.adk_agent's, not a drifted copy.
    assert get_synthetic_deployment_event() == get_synthetic_ride_event()
