from types import SimpleNamespace

import pytest

from app.agents import GeminiStoryCopyError, VertexAIGeminiStoryCopyTransport


def _response() -> dict[str, object]:
    return {
        "title": "A Synthetic Ride",
        "chapters": [
            {
                "chapter_id": "chapter_01",
                "title": "Departure",
                "selection_rationale": "Establishes the ride.",
            }
        ],
    }


class RecordingModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def _transport(
    response: object,
) -> tuple[VertexAIGeminiStoryCopyTransport, RecordingModels]:
    models = RecordingModels(response)
    return (
        VertexAIGeminiStoryCopyTransport(SimpleNamespace(models=models), model="gemini-test"),
        models,
    )


def test_vertex_story_copy_builds_schema_constrained_request() -> None:
    transport, models = _transport(SimpleNamespace(parsed=_response(), text=None))

    result = transport.generate_story_copy(
        prompt="Write in English.",
        story_payload={"source_title": "Synthetic", "chapters": []},
    )

    assert result == _response()
    assert len(models.calls) == 1
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["contents"][0] == "Write in English."  # type: ignore[index]
    config = call["config"]
    assert config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["additionalProperties"] is False
    chapter_schema = config.response_json_schema["properties"]["chapters"]["items"]
    assert chapter_schema["additionalProperties"] is False


def test_vertex_story_copy_parses_json_text_fallback() -> None:
    transport, _ = _transport(
        SimpleNamespace(
            parsed=None,
            text=(
                '{"title":"A Synthetic Ride","chapters":'
                '[{"chapter_id":"chapter_01","title":"Departure",'
                '"selection_rationale":"Establishes the ride."}]}'
            ),
        )
    )

    result = transport.generate_story_copy(
        prompt="Write in English.",
        story_payload={"source_title": "Synthetic"},
    )

    assert result == _response()


@pytest.mark.parametrize(
    ("prompt", "payload"),
    (("", {"source_title": "Synthetic"}), ("Write.", {})),
)
def test_vertex_story_copy_rejects_empty_request_before_client_call(
    prompt: str,
    payload: dict[str, object],
) -> None:
    transport, models = _transport(SimpleNamespace(parsed=_response(), text=None))

    with pytest.raises(ValueError, match="non-empty"):
        transport.generate_story_copy(prompt=prompt, story_payload=payload)

    assert models.calls == []


def test_vertex_story_copy_converts_client_failure_to_safe_error() -> None:
    class FailingModels:
        def generate_content(self, **_kwargs: object) -> object:
            raise RuntimeError("sensitive provider detail")

    transport = VertexAIGeminiStoryCopyTransport(
        SimpleNamespace(models=FailingModels()), model="gemini-test"
    )

    with pytest.raises(GeminiStoryCopyError, match="request failed") as caught:
        transport.generate_story_copy(
            prompt="Write in English.",
            story_payload={"source_title": "Synthetic"},
        )

    assert "sensitive provider detail" not in str(caught.value)


def test_vertex_story_copy_rejects_missing_structured_response() -> None:
    transport, _ = _transport(SimpleNamespace(parsed=None, text=""))

    with pytest.raises(GeminiStoryCopyError, match="no structured story copy"):
        transport.generate_story_copy(
            prompt="Write in English.",
            story_payload={"source_title": "Synthetic"},
        )
