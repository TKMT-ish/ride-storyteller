from __future__ import annotations

import sys

import pytest

from app.agent_runtime import (
    GeminiConnectionProbeError,
    GoogleCloudRuntimeSettings,
    run_synthetic_gemini_probe,
)
from app.agent_runtime.gemini_probe import _create_vertex_ai_client


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


def test_synthetic_probe_wraps_an_unexpected_error_from_the_client_factory() -> None:
    def _factory(_settings: GoogleCloudRuntimeSettings) -> FakeClient:
        raise ValueError("network is unreachable")

    with pytest.raises(GeminiConnectionProbeError, match="probe failed") as excinfo:
        run_synthetic_gemini_probe(_settings(), client_factory=_factory)
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_synthetic_probe_lets_its_own_error_type_propagate_unchanged() -> None:
    def _factory(_settings: GoogleCloudRuntimeSettings) -> FakeClient:
        raise GeminiConnectionProbeError("already a probe error")

    with pytest.raises(GeminiConnectionProbeError, match="already a probe error"):
        run_synthetic_gemini_probe(_settings(), client_factory=_factory)


def test_default_client_factory_builds_a_vertex_ai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    captured: dict[str, object] = {}

    class FakeVertexClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeVertexClient)

    client = _create_vertex_ai_client(_settings())

    assert isinstance(client, FakeVertexClient)
    assert captured == {
        "vertexai": True,
        "project": "ride-storyteller",
        "location": "global",
    }


def test_default_client_factory_rejects_a_missing_google_genai_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import google

    monkeypatch.setitem(sys.modules, "google.genai", None)
    monkeypatch.delattr(google, "genai", raising=False)

    with pytest.raises(GeminiConnectionProbeError, match="SDK is not installed"):
        _create_vertex_ai_client(_settings())
