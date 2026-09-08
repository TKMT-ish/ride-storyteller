"""Synthetic-fixture tests for app.story_copy_probe.

`run_synthetic_story_copy_probe` was previously exercised only indirectly
(through the underlying `GeminiStoryCopyGenerator`, covered by
`tests/test_story_copy.py`): the probe's own wiring -- which model name
survives into the result, that the response-received flag and the
synthetic/private-data flags come out right, and that a Gemini failure
does not get swallowed into a false "succeeded" result -- had no direct
test. No network call: `VertexAIGeminiStoryCopyTransport.from_environment`
is monkeypatched with a fake transport, the same shape
`tests/test_gemini_probe.py` uses for its own probe module.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.agents import GeminiStoryCopyError, StoryOutputLanguage
from app.agents.vertex_story_copy import VertexAIGeminiStoryCopyTransport
from app.story_copy_probe import SyntheticStoryCopyProbe, run_synthetic_story_copy_probe


def _response() -> dict[str, object]:
    # chapter_ids must match app.demo.build_demo_story_plan's own three
    # chapters exactly -- GeminiStoryCopyGenerator rejects a response whose
    # structure the model has changed.
    return {
        "title": "A Synthetic Ride",
        "chapters": [
            {
                "chapter_id": "chapter_01",
                "title": "Departure",
                "selection_rationale": "Establishes the start of the ride.",
            },
            {
                "chapter_id": "chapter_02",
                "title": "Changing Scenery",
                "selection_rationale": "Marks a GPS-derived transition.",
            },
            {
                "chapter_id": "chapter_03",
                "title": "Arrival",
                "selection_rationale": "Closes the route.",
            },
        ],
    }


class FakeTransport:
    def __init__(self, response: Mapping[str, object], *, model: str = "gemini-2.5-flash") -> None:
        self.response = response
        self.model = model
        self.calls: list[dict[str, object]] = []

    def generate_story_copy(
        self, *, prompt: str, story_payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        self.calls.append({"prompt": prompt, "story_payload": dict(story_payload)})
        return self.response


def test_probe_reports_the_configured_transports_model(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport(_response(), model="gemini-2.5-pro")
    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport, "from_environment", classmethod(lambda cls: transport)
    )

    result = run_synthetic_story_copy_probe()

    assert result.model == "gemini-2.5-pro"
    assert len(transport.calls) == 1


def test_probe_always_requests_english_output_from_the_japanese_demo_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(_response())
    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport, "from_environment", classmethod(lambda cls: transport)
    )

    result = run_synthetic_story_copy_probe()

    assert result.language == StoryOutputLanguage.ENGLISH.value
    request = transport.calls[0]
    assert "in English" in str(request["prompt"])


def test_probe_marks_the_input_synthetic_and_never_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(_response())
    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport, "from_environment", classmethod(lambda cls: transport)
    )

    result = run_synthetic_story_copy_probe()

    assert result.synthetic_input is True
    assert result.private_data_used is False


def test_probe_chapter_count_and_response_received_reflect_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response()
    transport = FakeTransport(response)
    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport, "from_environment", classmethod(lambda cls: transport)
    )

    result = run_synthetic_story_copy_probe()

    assert result.chapter_count == len(response["chapters"])
    assert result.response_received is True


def test_probe_propagates_a_gemini_failure_rather_than_reporting_false_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTransport:
        model = "gemini-2.5-flash"

        def generate_story_copy(self, **_kwargs: object) -> Mapping[str, object]:
            raise RuntimeError("sensitive provider response")

    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport,
        "from_environment",
        classmethod(lambda cls: FailingTransport()),
    )

    with pytest.raises(GeminiStoryCopyError, match="unavailable") as caught:
        run_synthetic_story_copy_probe()

    assert "sensitive provider response" not in str(caught.value)


def test_probe_propagates_a_malformed_response_rather_than_reporting_false_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response()
    del response["chapters"][0]["title"]
    transport = FakeTransport(response)
    monkeypatch.setattr(
        VertexAIGeminiStoryCopyTransport, "from_environment", classmethod(lambda cls: transport)
    )

    with pytest.raises(GeminiStoryCopyError, match="invalid structured story copy"):
        run_synthetic_story_copy_probe()


def test_to_dict_carries_exactly_the_safe_fields_no_more_no_less() -> None:
    probe = SyntheticStoryCopyProbe(
        model="gemini-2.5-flash",
        language="en",
        chapter_count=3,
        response_received=True,
    )

    assert probe.to_dict() == {
        "model": "gemini-2.5-flash",
        "language": "en",
        "chapter_count": 3,
        "response_received": True,
        "synthetic_input": True,
        "private_data_used": False,
    }
