"""Validated data contracts passed between Day 1 components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum


class DecisionStatus(StrEnum):
    AWAITING_VIDEO_EVIDENCE = "awaiting_video_evidence"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class RetrievalStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class RoutePoint:
    """One normalized GPX track point using UTC and WGS84 coordinates."""

    timestamp: datetime
    latitude: float
    longitude: float
    elevation_m: float | None
    distance_from_start_m: float
    speed_mps: float | None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("route point timestamp must be timezone-aware")
        Location(self.latitude, self.longitude)
        if self.distance_from_start_m < 0:
            raise ValueError("distance_from_start_m must be non-negative")
        if self.speed_mps is not None and self.speed_mps < 0:
            raise ValueError("speed_mps must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "distance_from_start_m": self.distance_from_start_m,
            "speed_mps": self.speed_mps,
        }


@dataclass(frozen=True)
class RouteSummary:
    point_count: int
    start_time: datetime
    end_time: datetime
    total_distance_m: float
    duration_s: float
    elevation_gain_m: float
    elevation_loss_m: float

    def __post_init__(self) -> None:
        if self.point_count < 1:
            raise ValueError("point_count must be positive")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("route summary times must be timezone-aware")
        if self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")
        values = (
            self.total_distance_m,
            self.duration_s,
            self.elevation_gain_m,
            self.elevation_loss_m,
        )
        if min(values) < 0:
            raise ValueError("route summary values must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "point_count": self.point_count,
            "start_time": self.start_time.isoformat().replace("+00:00", "Z"),
            "end_time": self.end_time.isoformat().replace("+00:00", "Z"),
            "total_distance_m": self.total_distance_m,
            "duration_s": self.duration_s,
            "elevation_gain_m": self.elevation_gain_m,
            "elevation_loss_m": self.elevation_loss_m,
        }


@dataclass(frozen=True)
class StoryChapter:
    chapter_id: str
    title: str
    event_id: str
    start_time: datetime
    end_time: datetime
    narrative_role: str
    selection_rationale: str
    target_duration_s: float

    def __post_init__(self) -> None:
        if not all(
            (
                self.chapter_id,
                self.title,
                self.event_id,
                self.narrative_role,
                self.selection_rationale,
            )
        ):
            raise ValueError("story chapter identifiers and text are required")
        if self.end_time < self.start_time:
            raise ValueError("chapter end_time must not be before start_time")
        if self.target_duration_s <= 0:
            raise ValueError("chapter target_duration_s must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "event_id": self.event_id,
            "start_time": self.start_time.isoformat().replace("+00:00", "Z"),
            "end_time": self.end_time.isoformat().replace("+00:00", "Z"),
            "narrative_role": self.narrative_role,
            "selection_rationale": self.selection_rationale,
            "target_duration_s": self.target_duration_s,
        }


@dataclass(frozen=True)
class StoryPlan:
    title: str
    target_duration_s: float
    chapters: tuple[StoryChapter, ...]
    selected_event_ids: tuple[str, ...]
    planning_provider: str

    def __post_init__(self) -> None:
        if not self.title or not self.chapters or not self.planning_provider:
            raise ValueError("story plan title, chapters, and provider are required")
        if not 300 <= self.target_duration_s <= 600:
            raise ValueError("target_duration_s must be between 300 and 600 seconds")
        if len(self.chapters) != len(self.selected_event_ids):
            raise ValueError("each chapter must refer to one selected event")

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "target_duration_s": self.target_duration_s,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
            "selected_event_ids": list(self.selected_event_ids),
            "planning_provider": self.planning_provider,
        }


def _score(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")


@dataclass(frozen=True)
class VideoQuery:
    asset_name_hint: str
    clip_start_offset_s: float = 0.0
    clip_end_offset_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.asset_name_hint:
            raise ValueError("asset_name_hint is required")
        if self.clip_start_offset_s < 0 or self.clip_end_offset_s < self.clip_start_offset_s:
            raise ValueError("clip offsets must be non-negative and ordered")


@dataclass(frozen=True)
class GpsEvent:
    event_id: str
    event_type: str
    start_time: datetime
    end_time: datetime
    location: Location
    importance_hint: float
    evidence: tuple[str, ...]
    video_query: VideoQuery | dict[str, object]

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise ValueError("event_id and event_type are required")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("event times must be timezone-aware UTC timestamps")
        if self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")
        _score(self.importance_hint, "importance_hint")
        if isinstance(self.video_query, dict):
            object.__setattr__(self, "video_query", VideoQuery(**self.video_query))


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    provider: str
    name: str
    mime_type: str
    duration_s: float
    source_uri: str
    retrieval_status: RetrievalStatus = RetrievalStatus.FOUND

    def __post_init__(self) -> None:
        if not all((self.asset_id, self.provider, self.name, self.mime_type, self.source_uri)):
            raise ValueError("media asset identifiers are required")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")


@dataclass(frozen=True)
class VideoAnalysis:
    asset_id: str
    start_offset_s: float
    end_offset_s: float
    visual_description: str
    road_type: str
    scenery_tags: tuple[str, ...]
    weather_visible: str
    visual_interest_score: float
    story_relevance_score: float
    confidence: float
    analysis_provider: str

    def __post_init__(self) -> None:
        if not self.asset_id or not self.visual_description or not self.analysis_provider:
            raise ValueError("analysis identifiers and description are required")
        if self.start_offset_s < 0 or self.end_offset_s < self.start_offset_s:
            raise ValueError("analysis offsets must be non-negative and ordered")
        _score(self.visual_interest_score, "visual_interest_score")
        _score(self.story_relevance_score, "story_relevance_score")
        _score(self.confidence, "confidence")


@dataclass(frozen=True)
class StoryDecision:
    event_id: str
    needs_video_evidence: bool
    reason: str
    asset_name_hint: str | None
    decision_status: DecisionStatus
    updated_story_role: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason:
            raise ValueError("event_id and reason are required")
        if self.needs_video_evidence and not self.asset_name_hint:
            raise ValueError("asset_name_hint is required when video evidence is needed")
        if self.decision_status is DecisionStatus.ACCEPTED and not self.updated_story_role:
            raise ValueError("accepted decisions require updated_story_role")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["decision_status"] = self.decision_status.value
        return data
