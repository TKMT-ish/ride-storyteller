"""Minimal, private-media-safe Gemini connection verification for Vertex AI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .google_config import GoogleCloudRuntimeSettings

_SYNTHETIC_PROMPT = "Reply with exactly: RIDE_STORYTELLER_GEMINI_OK"


class GeminiProbeModels(Protocol):
    def generate_content(
        self, *, model: str, contents: str, config: dict[str, object]
    ) -> object: ...


class GeminiProbeClient(Protocol):
    models: GeminiProbeModels


class GeminiConnectionProbeError(RuntimeError):
    """A non-sensitive Gemini connection failure suitable for a setup screen."""


@dataclass(frozen=True)
class GeminiConnectionProbe:
    """Success metadata only; generated text is never retained or logged."""

    model: str
    response_received: bool

    def to_dict(self) -> dict[str, object]:
        return {"model": self.model, "response_received": self.response_received}


def run_synthetic_gemini_probe(
    settings: GoogleCloudRuntimeSettings,
    *,
    client_factory: Callable[[GoogleCloudRuntimeSettings], GeminiProbeClient] | None = None,
) -> GeminiConnectionProbe:
    """Make one short Gemini request without reading a GPX file or media asset."""
    if settings.status != "configuration_present":
        missing = ", ".join(settings.missing_configuration)
        raise GeminiConnectionProbeError(f"Google Cloud configuration is incomplete: {missing}")

    factory = client_factory or _create_vertex_ai_client
    try:
        client = factory(settings)
        response = client.models.generate_content(
            model=settings.model,
            contents=_SYNTHETIC_PROMPT,
            config={
                "temperature": 0,
                "max_output_tokens": 32,
                "thinking_config": {"thinking_budget": 0},
            },
        )
    except GeminiConnectionProbeError:
        raise
    except Exception as error:
        raise GeminiConnectionProbeError("Gemini connection probe failed") from error

    response_text = getattr(response, "text", None)
    if not isinstance(response_text, str) or not response_text.strip():
        raise GeminiConnectionProbeError("Gemini connection probe returned no text")
    return GeminiConnectionProbe(model=settings.model, response_received=True)


def _create_vertex_ai_client(settings: GoogleCloudRuntimeSettings) -> GeminiProbeClient:
    try:
        from google import genai
    except ImportError as error:
        raise GeminiConnectionProbeError("google-genai SDK is not installed") from error
    return genai.Client(
        vertexai=True,
        project=settings.project,
        location=settings.location,
    )
