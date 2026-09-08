from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent_runtime import (
    AdkSyntheticRunError,
    GoogleCloudRuntimeSettings,
    build_ride_storyteller_adk_app,
    get_synthetic_ride_event,
    run_synthetic_adk_demo,
)
from app.agent_runtime import adk_agent as adk_agent_module


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


def _part(*, called_tool: bool = False, text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        function_call=SimpleNamespace() if called_tool else None,
        text=text,
    )


def _event(*parts: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=SimpleNamespace(parts=list(parts)))


class _FakeInMemoryRunner:
    """A synthetic-fixture stand-in for google.adk.runners.InMemoryRunner.

    Never calls a real model; the events it returns (or the error it
    raises) are set per test through class attributes so run_synthetic_adk_demo's
    own event-parsing logic -- not ADK's -- is what each test exercises.
    """

    events: list[SimpleNamespace] = []
    raises: Exception | None = None

    def __init__(self, *, app: object) -> None:
        self.app = app

    async def run_debug(self, prompt: str, *, quiet: bool = False) -> list[SimpleNamespace]:
        if self.raises is not None:
            raise self.raises
        return self.events


def _run_with_fake_events(monkeypatch: pytest.MonkeyPatch, events: list[SimpleNamespace]) -> object:
    fake = type("_FakeInMemoryRunner", (_FakeInMemoryRunner,), {"events": events})
    monkeypatch.setattr(adk_agent_module, "InMemoryRunner", fake)
    return asyncio.run(run_synthetic_adk_demo(_settings()))


def test_run_synthetic_adk_demo_succeeds_when_the_tool_is_called_and_text_follows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_with_fake_events(
        monkeypatch, [_event(_part(called_tool=True), _part(text="evidence is not needed"))]
    )
    assert run.model == "gemini-2.5-flash"
    assert run.tool_called is True
    assert run.final_response_received is True
    assert run.to_dict() == {
        "model": "gemini-2.5-flash",
        "final_response_received": True,
        "tool_called": True,
    }


def test_run_synthetic_adk_demo_reads_the_tool_call_and_text_from_separate_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The tool-call event and the final-text event are two separate turns,
    # not two parts of the same event; the parser must accumulate across events.
    run = _run_with_fake_events(
        monkeypatch,
        [_event(_part(called_tool=True)), _event(_part(text="evidence is not needed"))],
    )
    assert run.tool_called is True
    assert run.final_response_received is True


def test_run_synthetic_adk_demo_fails_closed_when_the_tool_is_never_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(AdkSyntheticRunError, match="did not call its required tool"):
        _run_with_fake_events(monkeypatch, [_event(_part(text="an answer with no tool call"))])


def test_run_synthetic_adk_demo_fails_closed_when_no_final_text_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(AdkSyntheticRunError, match="returned no final text"):
        _run_with_fake_events(monkeypatch, [_event(_part(called_tool=True))])


def test_run_synthetic_adk_demo_fails_closed_on_a_blank_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Whitespace-only text is not a real final response.
    with pytest.raises(AdkSyntheticRunError, match="returned no final text"):
        _run_with_fake_events(monkeypatch, [_event(_part(called_tool=True), _part(text="   "))])


def test_run_synthetic_adk_demo_wraps_a_runner_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = type(
        "_FakeInMemoryRunner", (_FakeInMemoryRunner,), {"raises": RuntimeError("network down")}
    )
    monkeypatch.setattr(adk_agent_module, "InMemoryRunner", fake)

    with pytest.raises(AdkSyntheticRunError, match="synthetic demo failed") as excinfo:
        asyncio.run(run_synthetic_adk_demo(_settings()))
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_run_synthetic_adk_demo_rejects_incomplete_configuration_before_running() -> None:
    # An incomplete configuration must fail before InMemoryRunner is ever
    # constructed -- this test leaves the real InMemoryRunner in place to
    # prove that path is never reached.
    incomplete = GoogleCloudRuntimeSettings("", "global", "gemini-2.5-flash", "true")
    with pytest.raises(AdkSyntheticRunError, match="configuration is incomplete"):
        asyncio.run(run_synthetic_adk_demo(incomplete))
