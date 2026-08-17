import pytest

from app.agents import PrototypeOrchestrator, RuleBasedStoryAgent
from app.contracts import DecisionStatus
from app.mcp import MockMediaSearchTool
from app.video import GeminiVideoAnalysisError, GeminiVideoAnalyzer

from .test_orchestrator import _asset, build_demo_event


class RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.request: dict[str, object] | None = None

    def analyze_clip(
        self,
        *,
        source_uri: str,
        mime_type: str,
        start_s: float,
        end_s: float,
        prompt: str,
    ) -> dict[str, object]:
        self.request = {
            "source_uri": source_uri,
            "mime_type": mime_type,
            "start_s": start_s,
            "end_s": end_s,
            "prompt": prompt,
        }
        return self.response


class UnavailableTransport:
    def analyze_clip(
        self,
        *,
        source_uri: str,
        mime_type: str,
        start_s: float,
        end_s: float,
        prompt: str,
    ) -> dict[str, object]:
        raise ConnectionError("network unavailable")


def _response() -> dict[str, object]:
    return {
        "visual_description": "A rider follows a winding paved road.",
        "road_type": "paved road",
        "scenery_tags": ["road", "hills"],
        "weather_visible": "clear",
        "visual_interest_score": 0.75,
        "story_relevance_score": 0.70,
        "confidence": 0.80,
    }


def test_gemini_adapter_maps_a_structured_response_without_live_gemini() -> None:
    transport = RecordingTransport(_response())
    analysis = GeminiVideoAnalyzer(transport).analyze(_asset(), start_s=5.0, end_s=15.0)

    assert analysis.asset_id == "asset-1"
    assert analysis.analysis_provider == "gemini"
    assert analysis.scenery_tags == ("road", "hills")
    assert transport.request is not None
    assert transport.request["source_uri"] == "box://test"
    assert transport.request["mime_type"] == "video/mp4"
    assert "only visually supported facts" in str(transport.request["prompt"])


def test_gemini_adapter_rejects_malformed_model_output() -> None:
    malformed = _response()
    malformed["scenery_tags"] = "road"

    try:
        GeminiVideoAnalyzer(RecordingTransport(malformed)).analyze(
            _asset(), start_s=5.0, end_s=15.0
        )
    except GeminiVideoAnalysisError as error:
        assert "invalid structured analysis" in str(error)
    else:
        raise AssertionError("malformed Gemini output must be rejected")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("visual_description", ""),
        ("road_type", None),
        ("weather_visible", 42),
        ("visual_interest_score", True),
        ("story_relevance_score", "0.7"),
        ("confidence", None),
        ("visual_interest_score", -0.01),
        ("story_relevance_score", 1.01),
    ),
)
def test_gemini_adapter_rejects_invalid_required_fields(
    field: str, invalid_value: object
) -> None:
    malformed = _response()
    malformed[field] = invalid_value

    with pytest.raises(GeminiVideoAnalysisError, match="invalid structured analysis"):
        GeminiVideoAnalyzer(RecordingTransport(malformed)).analyze(
            _asset(), start_s=5.0, end_s=15.0
        )


def test_gemini_adapter_rejects_missing_required_field() -> None:
    malformed = _response()
    del malformed["confidence"]

    with pytest.raises(GeminiVideoAnalysisError, match="invalid structured analysis"):
        GeminiVideoAnalyzer(RecordingTransport(malformed)).analyze(
            _asset(), start_s=5.0, end_s=15.0
        )


def test_orchestrator_requests_human_review_when_gemini_is_unavailable() -> None:
    result = PrototypeOrchestrator(
        RuleBasedStoryAgent(),
        MockMediaSearchTool(_asset()),
        GeminiVideoAnalyzer(UnavailableTransport()),
    ).run(build_demo_event())

    assert result.decision_status is DecisionStatus.NEEDS_HUMAN_REVIEW
    assert result.needs_video_evidence is True
