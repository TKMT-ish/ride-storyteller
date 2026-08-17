"""Vertex AI Gemini transport for sanitized synthetic Story Plan prose."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from google import genai
from google.genai import types

from app.agent_runtime import GoogleCloudRuntimeSettings

from .story_copy import GeminiStoryCopyError


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


_STORY_COPY_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "chapters": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chapter_id": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "selection_rationale": {"type": "string", "minLength": 1},
                },
                "required": ["chapter_id", "title", "selection_rationale"],
            },
        },
    },
    "required": ["title", "chapters"],
}


class VertexAIGeminiStoryCopyTransport:
    """Call Gemini only when explicitly invoked with sanitized story metadata."""

    def __init__(self, client: _GenaiClient, *, model: str) -> None:
        if not model.strip():
            raise ValueError("Gemini model must be configured")
        self.client = client
        self.model = model.strip()

    @classmethod
    def from_environment(cls) -> "VertexAIGeminiStoryCopyTransport":
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

    def generate_story_copy(
        self,
        *,
        prompt: str,
        story_payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        if not prompt.strip() or not story_payload:
            raise ValueError("story-copy prompt and payload must be non-empty")
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=_STORY_COPY_SCHEMA,
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
            raise GeminiStoryCopyError("Vertex AI Gemini story-copy request failed") from error
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
            raise GeminiStoryCopyError(
                "Vertex AI Gemini returned invalid JSON story copy"
            ) from error
        if isinstance(decoded, dict):
            return decoded
    raise GeminiStoryCopyError("Vertex AI Gemini returned no structured story copy")
