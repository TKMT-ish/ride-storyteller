from types import SimpleNamespace

import pytest

from app.contracts import MediaAsset
from app.video import (
    GeminiVideoAnalysisError,
    GeminiVideoAnalyzer,
    VertexAIGeminiVideoTransport,
)


def _analysis() -> dict[str, object]:
    return {
        "visual_description": "A synthetic road scene.",
        "road_type": "paved",
        "scenery_tags": ["road"],
        "weather_visible": "clear",
        "visual_interest_score": 0.7,
        "story_relevance_score": 0.8,
        "confidence": 0.9,
    }


class RecordingModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def _transport(response: object) -> tuple[VertexAIGeminiVideoTransport, RecordingModels]:
    models = RecordingModels(response)
    client = SimpleNamespace(models=models)
    return VertexAIGeminiVideoTransport(client, model="gemini-test"), models


def test_vertex_transport_builds_schema_constrained_gcs_video_request() -> None:
    transport, models = _transport(SimpleNamespace(parsed=_analysis(), text=None))

    result = transport.analyze_clip(
        source_uri="gs://approved-bucket/synthetic-test.mp4",
        mime_type="video/mp4",
        start_s=5,
        end_s=15,
        prompt="Analyze only the supplied interval.",
    )

    assert result == _analysis()
    assert len(models.calls) == 1
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    parts = call["contents"]
    assert isinstance(parts, list)
    video_part = parts[0]
    assert video_part.file_data.file_uri == "gs://approved-bucket/synthetic-test.mp4"
    assert video_part.video_metadata.start_offset == "5.000s"
    assert video_part.video_metadata.end_offset == "15.000s"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "source_uri",
    (
        "/Users/private/video.mp4",
        "box://asset/video.mp4",
        "https://example.com/video.mp4",
        "gs://bucket",
    ),
)
def test_vertex_transport_rejects_non_gcs_or_incomplete_sources_before_call(
    source_uri: str,
) -> None:
    transport, models = _transport(SimpleNamespace(parsed=_analysis(), text=None))

    with pytest.raises(ValueError, match="approved gs://"):
        transport.analyze_clip(
            source_uri=source_uri,
            mime_type="video/mp4",
            start_s=0,
            end_s=10,
            prompt="Analyze.",
        )

    assert models.calls == []


def test_vertex_transport_parses_json_text_fallback() -> None:
    transport, _ = _transport(
        SimpleNamespace(parsed=None, text='{"visual_description":"synthetic"}')
    )

    result = transport.analyze_clip(
        source_uri="gs://approved-bucket/synthetic-test.mp4",
        mime_type="video/mp4",
        start_s=0,
        end_s=10,
        prompt="Analyze.",
    )

    assert result == {"visual_description": "synthetic"}


def test_vertex_transport_converts_client_failures_to_safe_error() -> None:
    class FailingModels:
        def generate_content(self, **_kwargs: object) -> object:
            raise RuntimeError("sensitive provider detail")

    transport = VertexAIGeminiVideoTransport(
        SimpleNamespace(models=FailingModels()), model="gemini-test"
    )

    with pytest.raises(GeminiVideoAnalysisError, match="request failed") as caught:
        transport.analyze_clip(
            source_uri="gs://approved-bucket/synthetic-test.mp4",
            mime_type="video/mp4",
            start_s=0,
            end_s=10,
            prompt="Analyze.",
        )

    assert "sensitive provider detail" not in str(caught.value)


def test_vertex_transport_integrates_with_stable_video_analysis_contract() -> None:
    transport, _ = _transport(SimpleNamespace(parsed=_analysis(), text=None))
    asset = MediaAsset(
        asset_id="synthetic-asset",
        provider="gcs",
        name="synthetic-test.mp4",
        mime_type="video/mp4",
        duration_s=30,
        source_uri="gs://approved-bucket/synthetic-test.mp4",
    )

    analysis = GeminiVideoAnalyzer(transport).analyze(asset, start_s=5, end_s=15)

    assert analysis.asset_id == "synthetic-asset"
    assert analysis.analysis_provider == "gemini"
    assert analysis.story_relevance_score == 0.8
