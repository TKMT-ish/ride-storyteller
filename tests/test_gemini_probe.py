from __future__ import annotations

import pytest

from app.agent_runtime import (
    GeminiConnectionProbeError,
    GoogleCloudRuntimeSettings,
    run_synthetic_gemini_probe,
)


class FakeResponse:
    text = "RIDE_STORYTELLER_GEMINI_OK"


class FakeModels:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def generate_content(
        self, *, model: str, contents: str, config: dict[str, object]
    ) -> FakeResponse:
        self.request = {"model": model, "contents": contents, "config": config}
        return FakeResponse()


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


def _settings() -> GoogleCloudRuntimeSettings:
    return GoogleCloudRuntimeSettings(
        project="ride-storyteller",
        location="global",
        model="gemini-2.5-flash",
        use_vertex_ai="true",
    )


def test_synthetic_probe_uses_only_the_fixed_non_private_prompt() -> None:
    client = FakeClient()

    result = run_synthetic_gemini_probe(_settings(), client_factory=lambda _: client)

    assert result.to_dict() == {"model": "gemini-2.5-flash", "response_received": True}
    assert client.models.request == {
        "model": "gemini-2.5-flash",
        "contents": "Reply with exactly: RIDE_STORYTELLER_GEMINI_OK",
        "config": {
            "temperature": 0,
            "max_output_tokens": 32,
            "thinking_config": {"thinking_budget": 0},
        },
    }


def test_synthetic_probe_rejects_incomplete_configuration() -> None:
    incomplete = GoogleCloudRuntimeSettings("", "global", "gemini-2.5-flash", "true")

    with pytest.raises(GeminiConnectionProbeError, match="configuration is incomplete"):
        run_synthetic_gemini_probe(incomplete)


def test_synthetic_probe_rejects_an_empty_model_response() -> None:
    class EmptyResponse:
        text = ""

    class EmptyModels:
        def generate_content(self, **_: object) -> EmptyResponse:
            return EmptyResponse()

    class EmptyClient:
        models = EmptyModels()

    with pytest.raises(GeminiConnectionProbeError, match="returned no text"):
        run_synthetic_gemini_probe(_settings(), client_factory=lambda _: EmptyClient())
