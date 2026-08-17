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
