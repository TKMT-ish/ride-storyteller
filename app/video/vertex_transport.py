"""Vertex AI Gemini transport for an already-approved GCS video object.

This module never uploads local media. It accepts only a ``gs://`` URI supplied
by an authorized caller and constrains the model response with a JSON schema.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
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
        "rider_visible": {"type": "string", "enum": ["none", "small", "large"]},
        "stationary": {"type": "string", "enum": ["yes", "no"]},
        "photogenic_score": {"type": "number", "minimum": 0, "maximum": 1},
        "highlight_subject": {
            "type": "string",
            "enum": [
                "none",
                "vista",
                "mountains",
                "water",
                "cityscape",
                "landmark",
                "winding_road",
                "sky",
                "rest_stop",
            ],
        },
        "road_event": {
            "type": "string",
            "enum": [
                "none",
                "joining_highway",
                "leaving_highway",
                "entering_town",
                "leaving_town",
                "setting_off",
                "pulling_in",
            ],
        },
        "place_kind": {
            "type": "string",
            "enum": [
                "none",
                "fuel",
                "eatery",
                "lodging",
                "attraction",
                "lookout",
                "shop",
                "ferry",
                "residential",
                "other",
            ],
        },
        "place_name": {"type": "string"},
        "visual_interest_score": {"type": "number", "minimum": 0, "maximum": 1},
        "story_relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "visual_description",
        "road_type",
        "scenery_tags",
        "weather_visible",
        "rider_visible",
        "stationary",
        "road_event",
        "photogenic_score",
        "highlight_subject",
        "place_kind",
        "place_name",
        "visual_interest_score",
        "story_relevance_score",
        "confidence",
    ],
}


_RANKING_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "order": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
    "required": ["order"],
}

# Clips in one ranking call are labelled A, B, C ... so the model names them
# back by letter; the caller maps letters to its own identifiers. Letters,
# not identifiers, because an identifier is the caller's business and a
# model asked to echo one may not echo it exactly.
RANKING_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Vertex AI refuses a request with more video files than this (measured:
# 400 INVALID_ARGUMENT at twelve).
MAX_VIDEOS_PER_REQUEST = 10

# A judgement of a long ride is hundreds of requests over the better part
# of an hour, and on one real ride the 433rd was met with a connection
# reset. That is not the model refusing anything; it is the network, and
# treating it as a fault stopped the run and cost a restart. A request
# that never returned is asked again, a few times, with a pause -- and a
# request the model answered with an error is not, because asking twice
# is how a refusal gets paid for twice.
TRANSIENT_ATTEMPTS = 3
TRANSIENT_PAUSE_S = (2.0, 6.0)
# Matched by name so that this module needs to know nothing about the
# HTTP library underneath the client.
_TRANSIENT_NETWORK_FAILURES = frozenset(
    {
        "ReadError",
        "WriteError",
        "ConnectError",
        "RemoteProtocolError",
        "ReadTimeout",
        "WriteTimeout",
        "ConnectTimeout",
        "PoolTimeout",
    }
)
# The server saying "not now": rate limited, or briefly unavailable.
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _is_transient(error: BaseException) -> bool:
    """Whether this failure, or one under it, is worth asking again about."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        kind = type(current)
        if kind.__module__.split(".")[0] in {"httpx", "httpcore"}:
            if kind.__name__ in _TRANSIENT_NETWORK_FAILURES:
                return True
        if isinstance(current, ConnectionError | TimeoutError):
            return True
        code = getattr(current, "code", None)
        if kind.__module__.startswith("google.") and code in _TRANSIENT_STATUS_CODES:
            return True
        current = current.__cause__ or current.__context__
    return False


class VertexAIGeminiVideoTransport:
    """Analyze one approved GCS clip through Vertex AI Gemini.

    Client creation and the network call occur only when explicitly invoked.
    The returned mapping is validated again by :class:`GeminiVideoAnalyzer`.
    """

    def __init__(
        self,
        client: _GenaiClient,
        *,
        model: str,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        if not model.strip():
            raise ValueError("Gemini model must be configured")
        self.client = client
        self.model = model.strip()
        self._pause = pause

    def _generate(
        self,
        *,
        contents: list[types.Part | str],
        config: types.GenerateContentConfig,
        what: str,
    ) -> object:
        """One request, asked again after a transient network failure."""
        for attempt in range(TRANSIENT_ATTEMPTS):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except Exception as error:
                last_attempt = attempt == TRANSIENT_ATTEMPTS - 1
                if last_attempt or not _is_transient(error):
                    raise GeminiVideoAnalysisError(
                        f"Vertex AI Gemini {what} request failed"
                    ) from error
                self._pause(TRANSIENT_PAUSE_S[min(attempt, len(TRANSIENT_PAUSE_S) - 1)])
        raise AssertionError("unreachable")

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
        response = self._generate(contents=[video_part, prompt], config=config, what="video")
        return _response_mapping(response)

    def rank_clips(self, *, source_uris: list[str], mime_type: str, prompt: str) -> list[str]:
        """Show several clips in one request and get back their labels in order.

        Returns the labels (A, B, C ...) best first. The caller maps them to
        whatever the clips are; a label that comes back unknown or twice is an
        error, because a ranking with a hole in it is not a ranking.
        """
        if not 2 <= len(source_uris) <= MAX_VIDEOS_PER_REQUEST:
            raise ValueError("a ranking needs between two and ten clips")
        for uri in source_uris:
            _validate_request(uri, mime_type, 0.0, 1.0, prompt)
        contents: list[types.Part | str] = []
        for label, uri in zip(RANKING_LABELS, source_uris, strict=False):
            contents.append(f"Window {label}:")
            contents.append(types.Part(file_data=types.FileData(file_uri=uri, mime_type=mime_type)))
        contents.append(prompt)
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=_RANKING_SCHEMA,
        )
        response = self._generate(contents=contents, config=config, what="ranking")
        order = _response_mapping(response).get("order")
        if not isinstance(order, list):
            raise GeminiVideoAnalysisError("Vertex AI Gemini returned no ranking")
        # The model tends to answer "Window C" rather than "C"; the label is
        # the last letter of whatever it said.
        labels = [_last_letter(str(item)) for item in order]
        expected = list(RANKING_LABELS[: len(source_uris)])
        if sorted(labels) != sorted(expected):
            raise GeminiVideoAnalysisError("Vertex AI Gemini returned an incomplete ranking")
        return labels


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


def _last_letter(text: str) -> str:
    letters = [ch for ch in text.upper() if "A" <= ch <= "Z"]
    return letters[-1] if letters else ""


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
