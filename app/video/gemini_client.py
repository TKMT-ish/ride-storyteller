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


# What the two scores mean, with anchors. The first real ride was judged
# without these and came back flat -- 30 windows at exactly 0.66, 33 at
# exactly 0.54 -- because "score from 0 to 1" says nothing about what a 0.3
# or a 0.8 looks like on a road. A model asked to score without a rubric
# scores everything as "fine". These anchors are the rubric; they name what
# separates an ordinary minute of riding from one worth showing.
SCORING_RUBRIC = (
    "Score with the whole range, and expect most windows of a long ride to be "
    "ordinary. visual_interest_score: 0.2 = the view barely changes (stopped, a "
    "car park, a queue of traffic, a plain straight road with nothing beyond it); "
    "0.5 = steady riding on an ordinary road with little to look at; 0.8 = the "
    "scenery is clearly worth seeing (mountains, a gorge, coast, a river, a "
    "valley, a striking sky) or the road itself is (sweeping curves, a climb, a "
    "descent, a lean into a bend); 1.0 = exceptional, the shot of the day. "
    "story_relevance_score: how much this window tells a viewer where the ride "
    "went and what it was like. 0.2 = it could be anywhere; 0.5 = it shows the "
    "kind of road and landscape; 0.8 = a landmark, a turn-off, a summit, a "
    "change of terrain or weather, a departure or an arrival; 1.0 = a moment "
    "the whole ride would be told around. Reserve scores above 0.7 for windows "
    "that clearly stand out from the rest of the ride. Score each window on "
    "its own merits; do not assume every window deserves a middling score. "
    "rider_visible: 'none' when no part of the rider or their reflection is in "
    "the frame; 'small' when only a glove or a sleeve shows at the edge; 'large' "
    "when the rider's reflection in a mirror shows their body or helmet, or an "
    "arm, a helmet or a person standing in front of the camera takes a "
    "noticeable part of the frame -- a rider visible in the mirror is 'large'. "
    "stationary: 'yes' when the motorcycle does not move for the whole window "
    "(parked, waiting, stopped at a light), 'no' when it rides at any point. "
    "road_event: what the road is doing in this window -- 'joining_highway' "
    "when the bike merges onto a motorway or highway (an on-ramp, a merge lane, "
    "a junction onto a bigger road); 'leaving_highway' when it takes an exit or "
    "turns off a highway onto a smaller road; 'entering_town' when open road "
    "gives way to streets and buildings; 'leaving_town' when streets give way "
    "to open road; 'setting_off' when the bike starts moving from rest; "
    "'pulling_in' when it slows to a stop at a place; otherwise 'none'. "
    "photogenic_score: how much a travel photographer would want a frame of "
    "this window as a photograph -- composition, light, a clear subject, colour "
    "-- regardless of motion: 0.2 = nothing to frame (a plain road, a car park, "
    "traffic ahead); 0.5 = pleasant but ordinary; 0.8 = a frame worth keeping (a "
    "wide view opening up, a coastline, a mountain range, a striking town street, "
    "a landmark, dramatic light); 1.0 = the picture of the day. highlight_subject: "
    "what that picture is of -- 'vista' (a wide open view), 'mountains', 'water' "
    "(sea, lake, river), 'cityscape' (a town or city scene), 'landmark' (a bridge, "
    "a building, a monument, a sign for a place), 'winding_road' (the road itself "
    "as the subject), 'sky' (weather or light as the subject), 'rest_stop' (a "
    "stop with a view or a place worth seeing), or 'none'. place_kind: when the "
    "bike is at or arriving at a place, what the place is -- 'fuel' (a petrol "
    "station), 'eatery' (a cafe, restaurant, bakery, takeaway), 'lodging' (a "
    "hotel, motel, holiday park, its reception or its rooms), 'attraction' (a "
    "museum, gallery, memorial, visitor centre, a sight), 'lookout' (a viewpoint "
    "or viewing platform), 'shop' (a supermarket, a store, a dealership), 'ferry' "
    "(a terminal, a wharf, a vessel's deck), 'residential' (a private house, its "
    "driveway or garage), 'other' for any other place, or 'none' when the bike "
    "is simply on the road. place_name: the name of that place as written on a "
    "sign or building in the picture, exactly as written, or an empty string "
    "when no name is legible."
)


def _analysis_prompt(start_s: float, end_s: float) -> str:
    return (
        "Analyze only the requested motorcycle-video interval. Return JSON with "
        "visual_description, road_type, scenery_tags, weather_visible, "
        "rider_visible, stationary, road_event, photogenic_score, "
        "highlight_subject, place_kind, place_name, visual_interest_score, "
        "story_relevance_score, and confidence. "
        "Describe only visually supported facts; use 'unknown' when unclear. "
        + SCORING_RUBRIC
        + f" Requested interval: {start_s:.2f}s to {end_s:.2f}s."
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
        rider_visible=_optional_text(response, "rider_visible", default="unknown"),
        stationary=_optional_text(response, "stationary", default="unknown"),
        road_event=_optional_text(response, "road_event", default="unknown"),
        photogenic_score=_optional_score(response, "photogenic_score"),
        highlight_subject=_optional_text(response, "highlight_subject", default="unknown"),
        place_kind=_optional_text(response, "place_kind", default="unknown"),
        place_name=_optional_text(response, "place_name", default="").strip() or None,
    )


def _required_text(response: Mapping[str, object], key: str) -> str:
    value = response[key]
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{key} must be non-empty text")
    return value


def _optional_text(response: Mapping[str, object], key: str, *, default: str) -> str:
    value = response.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{key} must be text when present")
    return value


def _optional_score(response: Mapping[str, object], key: str) -> float | None:
    if response.get(key) is None:
        return None
    return _required_score(response, key)


def _required_score(response: Mapping[str, object], key: str) -> float:
    value = response[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be numeric")
    return float(value)
