"""Vertex AI Gemini transport for the Director pipeline.

Follows the same pattern as ``VertexAIGeminiStoryCopyTransport``:
a thin adapter that forwards a sanitized payload to Gemini and returns
the raw parsed response.  No API key is stored here; credentials come
from the ambient Google Cloud authentication configured by the caller.

The JSON schema enforces the four-field scene contract so that structural
errors are caught before ``_validated_gemini_script`` runs its semantic
checks.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from google import genai
from google.genai import types

from app.agent_runtime import GoogleCloudRuntimeSettings
from app.director import GeminiDirectorError


class _ModelsClient(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: list[str],
        config: types.GenerateContentConfig,
    ) -> object: ...


class _GenaiClient(Protocol):
    models: _ModelsClient


# JSON Schema for the Gemini director response.
# additionalProperties: false at the scene level matches _SCENE_KEYS in director.py.
_DIRECTOR_SCRIPT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scene_type": {
                        "type": "string",
                        "enum": ["hook", "build_up", "climax", "resolution"],
                    },
                    "event_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "transition_type": {
                        "type": "string",
                        "enum": ["cut"],
                    },
                    "overlay_text": {"type": ["string", "null"]},
                },
                "required": ["scene_type", "event_ids", "transition_type", "overlay_text"],
            },
        },
    },
    "required": ["scenes"],
}


class VertexAIGeminiDirectorTransport:
    """Call Gemini to compose a director script from a sanitized event payload.

    Instantiate via ``from_environment()`` for production use; pass a
    custom ``client`` and ``model`` in tests.
    """

    def __init__(self, client: _GenaiClient, *, model: str) -> None:
        if not model.strip():
            raise ValueError("Gemini model must be configured")
        self.client = client
        self.model = model.strip()

    @classmethod
    def from_environment(cls) -> "VertexAIGeminiDirectorTransport":
        settings = GoogleCloudRuntimeSettings.from_environment()
        if settings.status != "configuration_present":
            missing = ", ".join(settings.missing_configuration)
            raise ValueError(f"Google Cloud configuration is incomplete: {missing}")
        client = genai.Client(
            vertexai=True,
            project=settings.project,
            location=settings.location,
        )
        return cls(client, model=settings.model)

    def compose_script(
        self,
        *,
        prompt: str,
        story_payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        if not prompt.strip() or not story_payload:
            raise GeminiDirectorError(
                "director transport: prompt and payload must be non-empty"
            )
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=_DIRECTOR_SCRIPT_SCHEMA,
        )
        contents = [
            prompt,
            json.dumps(story_payload, ensure_ascii=True, sort_keys=True),
        ]
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except Exception as error:
            raise GeminiDirectorError(
                "Vertex AI Gemini director request failed"
            ) from error
        return _response_mapping(response)


def _response_mapping(response: object) -> Mapping[str, object]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, Mapping):
        return dict(parsed)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise GeminiDirectorError(
                "Vertex AI Gemini returned invalid JSON director script"
            ) from error
        if isinstance(decoded, dict):
            return decoded
    raise GeminiDirectorError("Vertex AI Gemini returned no structured director script")
