"""Structured Gemini video-analysis contract and fail-closed validation."""

from collections.abc import Mapping
from typing import Protocol

from app.contracts import MediaAsset, VideoAnalysis


class VideoAnalyzer(Protocol):
    def analyze(self, asset: MediaAsset, *, start_s: float, end_s: float) -> VideoAnalysis: ...


class GeminiVideoTransport(Protocol):
    """A verified Gemini SDK adapter must implement this boundary."""

    def analyze_clip(
        self,
        *,
        source_uri: str,
        mime_type: str,
        start_s: float,
        end_s: float,
        prompt: str,
    ) -> Mapping[str, object]: ...


class GeminiVideoAnalysisError(RuntimeError):
    """A non-sensitive failure that must be surfaced for human review."""


class GeminiVideoAnalyzer:
    """Turn a structured Gemini response into the project's stable contract.

    This class deliberately has no API-key lookup and no Gemini SDK dependency.
    The concrete Vertex transport is injected separately and accepts only an
    already-approved GCS object; no media upload occurs in this layer.
    """

    def __init__(self, transport: GeminiVideoTransport) -> None:
        self.transport = transport

    def analyze(self, asset: MediaAsset, *, start_s: float, end_s: float) -> VideoAnalysis:
        if start_s < 0 or end_s < start_s or end_s > asset.duration_s:
            raise ValueError("requested clip interval must be within the media asset")
        try:
            response = self.transport.analyze_clip(
                source_uri=asset.source_uri,
                mime_type=asset.mime_type,
                start_s=start_s,
                end_s=end_s,
                prompt=_analysis_prompt(start_s, end_s),
            )
            return _video_analysis_from_response(asset, start_s, end_s, response)
        except GeminiVideoAnalysisError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GeminiVideoAnalysisError(
                "Gemini returned an invalid structured analysis"
            ) from error
        except Exception as error:
            raise GeminiVideoAnalysisError("Gemini video analysis was unavailable") from error


class MockVideoAnalyzer:
    def __init__(self, analysis: VideoAnalysis) -> None:
        self.analysis = analysis
        self.calls = 0

    def analyze(self, asset: MediaAsset, *, start_s: float, end_s: float) -> VideoAnalysis:
        self.calls += 1
        if asset.asset_id != self.analysis.asset_id:
            raise ValueError("analysis fixture does not belong to the requested asset")
        return self.analysis


def _analysis_prompt(start_s: float, end_s: float) -> str:
    return (
        "Analyze only the requested motorcycle-video interval. Return JSON with "
        "visual_description, road_type, scenery_tags, weather_visible, "
        "visual_interest_score, story_relevance_score, and confidence. "
        "Describe only visually supported facts; use 'unknown' when unclear. "
        f"Requested interval: {start_s:.2f}s to {end_s:.2f}s."
    )


def _video_analysis_from_response(
    asset: MediaAsset, start_s: float, end_s: float, response: Mapping[str, object]
) -> VideoAnalysis:
    scenery_tags = response["scenery_tags"]
    if isinstance(scenery_tags, str) or not isinstance(scenery_tags, (list, tuple)):
        raise TypeError("scenery_tags must be a list of strings")
    if not all(isinstance(tag, str) and tag for tag in scenery_tags):
        raise TypeError("scenery_tags must contain non-empty strings")
    return VideoAnalysis(
        asset_id=asset.asset_id,
        start_offset_s=start_s,
        end_offset_s=end_s,
        visual_description=_required_text(response, "visual_description"),
        road_type=_required_text(response, "road_type"),
        scenery_tags=tuple(scenery_tags),
        weather_visible=_required_text(response, "weather_visible"),
        visual_interest_score=_required_score(response, "visual_interest_score"),
        story_relevance_score=_required_score(response, "story_relevance_score"),
        confidence=_required_score(response, "confidence"),
        analysis_provider="gemini",
    )


def _required_text(response: Mapping[str, object], key: str) -> str:
    value = response[key]
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{key} must be non-empty text")
    return value


def _required_score(response: Mapping[str, object], key: str) -> float:
    value = response[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be numeric")
    return float(value)
