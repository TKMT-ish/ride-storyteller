from types import SimpleNamespace

import pytest

from app.agent_runtime import google_config
from app.agents.vertex_director import VertexAIGeminiDirectorTransport
from app.director import GeminiDirectorError


def _response() -> dict[str, object]:
    return {
        "scenes": [
            {
                "scene_type": "hook",
                "event_ids": ["event_01"],
                "transition_type": "cut",
                "overlay_text": None,
            }
        ]
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
) -> tuple[VertexAIGeminiDirectorTransport, RecordingModels]:
    models = RecordingModels(response)
    return (
        VertexAIGeminiDirectorTransport(SimpleNamespace(models=models), model="gemini-test"),
        models,
    )


def test_vertex_director_rejects_blank_model() -> None:
    with pytest.raises(ValueError, match="model must be configured"):
        VertexAIGeminiDirectorTransport(SimpleNamespace(models=None), model="   ")


def test_vertex_director_builds_schema_constrained_request() -> None:
    transport, models = _transport(SimpleNamespace(parsed=_response(), text=None))

    result = transport.compose_script(
        prompt="Compose the scenes.",
        story_payload={"source_title": "Synthetic", "events": []},
    )

    assert result == _response()
    assert len(models.calls) == 1
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["contents"][0] == "Compose the scenes."  # type: ignore[index]
    config = call["config"]
    assert config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["additionalProperties"] is False
    scene_schema = config.response_json_schema["properties"]["scenes"]["items"]
    assert scene_schema["additionalProperties"] is False
    assert scene_schema["properties"]["scene_type"]["enum"] == [
        "hook",
        "build_up",
        "climax",
        "resolution",
    ]


def test_vertex_director_parses_json_text_fallback() -> None:
    transport, _ = _transport(
        SimpleNamespace(
            parsed=None,
            text=(
                '{"scenes":[{"scene_type":"hook","event_ids":["event_01"],'
                '"transition_type":"cut","overlay_text":null}]}'
            ),
        )
    )

    result = transport.compose_script(
        prompt="Compose the scenes.",
        story_payload={"source_title": "Synthetic"},
    )

    assert result == _response()


def test_vertex_director_rejects_invalid_json_text() -> None:
    transport, _ = _transport(SimpleNamespace(parsed=None, text="not json"))

    with pytest.raises(GeminiDirectorError, match="invalid JSON director script"):
        transport.compose_script(
            prompt="Compose the scenes.",
            story_payload={"source_title": "Synthetic"},
        )


@pytest.mark.parametrize(
    ("prompt", "payload"),
    (("", {"source_title": "Synthetic"}), ("Compose.", {})),
)
def test_vertex_director_rejects_empty_request_before_client_call(
    prompt: str,
    payload: dict[str, object],
) -> None:
    transport, models = _transport(SimpleNamespace(parsed=_response(), text=None))

    with pytest.raises(GeminiDirectorError, match="non-empty"):
        transport.compose_script(prompt=prompt, story_payload=payload)

    assert models.calls == []


def test_vertex_director_converts_client_failure_to_safe_error() -> None:
    class FailingModels:
        def generate_content(self, **_kwargs: object) -> object:
            raise RuntimeError("sensitive provider detail")

    transport = VertexAIGeminiDirectorTransport(
        SimpleNamespace(models=FailingModels()), model="gemini-test"
    )

    with pytest.raises(GeminiDirectorError, match="request failed") as caught:
        transport.compose_script(
            prompt="Compose the scenes.",
            story_payload={"source_title": "Synthetic"},
        )

    assert "sensitive provider detail" not in str(caught.value)


def test_vertex_director_rejects_missing_structured_response() -> None:
    transport, _ = _transport(SimpleNamespace(parsed=None, text=""))

    with pytest.raises(GeminiDirectorError, match="no structured director script"):
        transport.compose_script(
            prompt="Compose the scenes.",
            story_payload={"source_title": "Synthetic"},
        )


def test_vertex_director_rejects_non_mapping_parsed_and_falls_back_to_text() -> None:
    transport, _ = _transport(
        SimpleNamespace(
            parsed=["not", "a", "mapping"],
            text='{"scenes":[{"scene_type":"hook","event_ids":["event_01"],'
            '"transition_type":"cut","overlay_text":null}]}',
        )
    )

    result = transport.compose_script(
        prompt="Compose the scenes.",
        story_payload={"source_title": "Synthetic"},
    )

    assert result == _response()


def test_vertex_director_from_environment_requires_configuration(monkeypatch) -> None:
    for key in (
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GEMINI_MODEL",
        "GOOGLE_GENAI_USE_VERTEXAI",
    ):
        monkeypatch.delenv(key, raising=False)
    # The settings fall back to the local .env file, so clearing the process
    # environment is not enough: on a configured machine this test would
    # otherwise pass its own configuration in and never raise.
    monkeypatch.setattr(google_config, "load_local_environment", dict)

    with pytest.raises(ValueError, match="Google Cloud configuration is incomplete"):
        VertexAIGeminiDirectorTransport.from_environment()
