from __future__ import annotations

import pytest

from app.agent_runtime import (
    AdkSyntheticRunError,
    GoogleCloudRuntimeSettings,
    build_ride_storyteller_adk_app,
    get_synthetic_ride_event,
)


def _settings() -> GoogleCloudRuntimeSettings:
    return GoogleCloudRuntimeSettings(
        project="ride-storyteller",
        location="global",
        model="gemini-2.5-flash",
        use_vertex_ai="true",
    )


def test_synthetic_tool_contains_no_real_material() -> None:
    event = get_synthetic_ride_event()

    assert event["event_id"] == "synthetic_scenery_change"
    assert event["contains_real_gpx"] is False
    assert event["contains_real_media"] is False
    assert "latitude" not in event
    assert "longitude" not in event


def test_adk_agent_uses_explicit_vertex_ai_configuration() -> None:
    app = build_ride_storyteller_adk_app(_settings())
    agent = app.root_agent

    assert agent is not None
    assert agent.name == "ride_storyteller_evidence_agent"
    assert len(agent.tools) == 1
    assert "real GPX" in str(agent.instruction)


def test_adk_agent_rejects_incomplete_cloud_configuration() -> None:
    incomplete = GoogleCloudRuntimeSettings("", "global", "gemini-2.5-flash", "true")

    with pytest.raises(AdkSyntheticRunError, match="configuration is incomplete"):
        build_ride_storyteller_adk_app(incomplete)
