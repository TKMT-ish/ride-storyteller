"""Vertex AI Gemini transport for an already-approved GCS video object.

This module never uploads local media. It accepts only a ``gs://`` URI supplied
by an authorized caller and constrains the model response with a JSON schema.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urlparse

from google import genai
from google.genai import types

from app.agent_runtime import GoogleCloudRuntimeSettings

from .gemini_client import GeminiVideoAnalysisError


class _ModelsClient(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: list[types.Part | str],
        config: types.GenerateContentConfig,
    ) -> object: ...


class _GenaiClient(Protocol):
    models: _ModelsClient


_VIDEO_ANALYSIS_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "visual_description": {"type": "string", "minLength": 1},
        "road_type": {"type": "string", "minLength": 1},
        "scenery_tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "weather_visible": {"type": "string", "minLength": 1},
        "visual_interest_score": {"type": "number", "minimum": 0, "maximum": 1},
        "story_relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "visual_description",
        "road_type",
        "scenery_tags",
        "weather_visible",
        "visual_interest_score",
        "story_relevance_score",
        "confidence",
    ],
}


class VertexAIGeminiVideoTransport:
    """Analyze one approved GCS clip through Vertex AI Gemini.

    Client creation and the network call occur only when explicitly invoked.
    The returned mapping is validated again by :class:`GeminiVideoAnalyzer`.
    """

    def __init__(self, client: _GenaiClient, *, model: str) -> None:
        if not model.strip():
            raise ValueError("Gemini model must be configured")
        self.client = client
        self.model = model.strip()

    @classmethod
    def from_environment(cls) -> "VertexAIGeminiVideoTransport":
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

    def analyze_clip(
        self,
        *,
        source_uri: str,
        mime_type: str,
        start_s: float,
        end_s: float,
        prompt: str,
    ) -> Mapping[str, object]:
        _validate_request(source_uri, mime_type, start_s, end_s, prompt)
        video_part = types.Part(
            file_data=types.FileData(file_uri=source_uri, mime_type=mime_type),
            video_metadata=types.VideoMetadata(
                start_offset=_seconds(start_s),
                end_offset=_seconds(end_s),
            ),
        )
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=_VIDEO_ANALYSIS_SCHEMA,
        )
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[video_part, prompt],
                config=config,
            )
        except Exception as error:
            raise GeminiVideoAnalysisError("Vertex AI Gemini video request failed") from error
        return _response_mapping(response)


def _validate_request(
    source_uri: str,
    mime_type: str,
    start_s: float,
    end_s: float,
    prompt: str,
) -> None:
    parsed = urlparse(source_uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError("Vertex AI video source must be an approved gs:// object URI")
    if not mime_type.startswith("video/"):
        raise ValueError("Vertex AI video source must use a video MIME type")
    if start_s < 0 or end_s <= start_s:
        raise ValueError("video interval must be positive and ordered")
    if not prompt.strip():
        raise ValueError("video analysis prompt must be non-empty")


def _seconds(value: float) -> str:
    return f"{value:.3f}s"


def _response_mapping(response: object) -> Mapping[str, object]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, Mapping):
        return dict(parsed)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise GeminiVideoAnalysisError(
                "Vertex AI Gemini returned invalid JSON video analysis"
            ) from error
        if isinstance(decoded, dict):
            return decoded
    raise GeminiVideoAnalysisError("Vertex AI Gemini returned no structured video analysis")
