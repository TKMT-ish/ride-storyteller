"""Describe the parts of a ride that no confirmed footage covers.

Gate 2 of docs/completion-roadmap-ja.md. Real-material verification found
that only a minority of a ride's GPS events are backed by footage, and that
the journey's departure and arrival may have none at all. The rule the
project has held throughout still applies: never invent footage for a moment
that was not filmed. So the parts of the ride with no confirmed clip become
*non-video* story segments instead — a chapter card, a movement on a map, a
passage of time — and this module produces the evidence for them.

A gap segment states only what the GPS track itself proves: how long the
ride continued, how far it went, and how much it climbed or descended
between two filmed moments. It makes no claim about what the camera saw,
because there was no camera running. That keeps the story honest about its
own coverage while still letting it move from departure to arrival.

`to_dict()` is deliberately aggregate-only: durations, distances, and
elevation deltas, with no coordinate, absolute capture timestamp, event ID,
asset ID, path, or file name. The absolute times on the dataclass exist only
so a caller can order segments against clips locally; they are never part of
the serialized view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.contracts import RoutePoint

JOURNEY_GAP_SCHEMA_VERSION = "journey-gap-segments-v1"

# A gap shorter than this is not worth its own story beat: at that length a
# chapter card would interrupt the ride rather than carry it forward.
DEFAULT_MINIMUM_GAP_S = 60.0


class JourneyGapKind(StrEnum):
    """Where an uncovered stretch sits relative to the confirmed footage."""

    BEFORE_FIRST_CLIP = "before_first_clip"
    BETWEEN_CLIPS = "between_clips"
    AFTER_LAST_CLIP = "after_last_clip"


class JourneyGapError(ValueError):
    """Raised when gap segments cannot be derived safely."""


@dataclass(frozen=True)
class JourneyGapSegment:
    """One uncovered stretch of the ride, described from GPS evidence only."""

    kind: JourneyGapKind
    start_time: datetime
    end_time: datetime
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("journey gap times must be timezone-aware")
        if self.end_time <= self.start_time:
            raise ValueError("journey gap must cover a positive duration")
        if self.distance_m < 0:
            raise ValueError("journey gap distance must not be negative")
        if self.elevation_gain_m < 0 or self.elevation_loss_m < 0:
            raise ValueError("journey gap elevation deltas must not be negative")

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, object]:
        """Aggregates only: no coordinate, capture timestamp, or identifier."""
        return {
            "kind": self.kind.value,
            "duration_s": round(self.duration_s, 3),
            "distance_m": round(self.distance_m, 3),
            "elevation_gain_m": round(self.elevation_gain_m, 3),
            "elevation_loss_m": round(self.elevation_loss_m, 3),
        }


@dataclass(frozen=True)
class JourneyGapPlan:
    """Every uncovered stretch of one ride, in chronological order."""

    segments: tuple[JourneyGapSegment, ...]

    def __post_init__(self) -> None:
        starts = [segment.start_time for segment in self.segments]
        if starts != sorted(starts):
            raise ValueError("journey gap segments must be chronological")
        for earlier, later in zip(self.segments, self.segments[1:], strict=False):
            if later.start_time < earlier.end_time:
                raise ValueError("journey gap segments must not overlap")

    @property
    def total_duration_s(self) -> float:
        return sum(segment.duration_s for segment in self.segments)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": JOURNEY_GAP_SCHEMA_VERSION,
            "segment_count": len(self.segments),
            "total_duration_s": round(self.total_duration_s, 3),
            "segments": [segment.to_dict() for segment in self.segments],
        }


def build_journey_gap_plan(
    points: tuple[RoutePoint, ...],
    covered_windows: tuple[tuple[datetime, datetime], ...],
    *,
    minimum_gap_s: float = DEFAULT_MINIMUM_GAP_S,
) -> JourneyGapPlan:
    """Derive the ride's uncovered stretches from its own track.

    `covered_windows` are the absolute time spans that confirmed footage
    already covers; they are merged before the gaps between them are taken,
    so overlapping or unordered windows are handled without inventing a gap
    that does not exist. A stretch shorter than `minimum_gap_s`, or one the
    track does not describe with at least two points, is left out rather than
    guessed at.
    """
    if minimum_gap_s <= 0:
        raise JourneyGapError("minimum gap must be positive")
    if len(points) < 2:
        raise JourneyGapError("journey gaps require at least two route points")
    for point, following in zip(points, points[1:], strict=False):
        if following.timestamp < point.timestamp:
            raise JourneyGapError("route points must be chronological")

    merged = _merged_windows(covered_windows)
    route_start, route_end = points[0].timestamp, points[-1].timestamp
    segments: list[JourneyGapSegment] = []
    cursor = route_start

    for window_start, window_end in merged:
        if window_start > cursor:
            kind = (
                JourneyGapKind.BEFORE_FIRST_CLIP
                if cursor == route_start
                else JourneyGapKind.BETWEEN_CLIPS
            )
            segment = _segment_for(
                points, cursor, min(window_start, route_end), kind, minimum_gap_s
            )
            if segment is not None:
                segments.append(segment)
        cursor = max(cursor, window_end)
        if cursor >= route_end:
            break

    if cursor < route_end:
        kind = JourneyGapKind.AFTER_LAST_CLIP if merged else JourneyGapKind.BEFORE_FIRST_CLIP
        segment = _segment_for(points, cursor, route_end, kind, minimum_gap_s)
        if segment is not None:
            segments.append(segment)

    return JourneyGapPlan(tuple(segments))


def _merged_windows(
    covered_windows: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[datetime, datetime], ...]:
    for start, end in covered_windows:
        if start.tzinfo is None or end.tzinfo is None:
            raise JourneyGapError("covered windows must be timezone-aware")
        if end <= start:
            raise JourneyGapError("covered windows must cover a positive duration")
    merged: list[list[datetime]] = []
    for start, end in sorted(covered_windows):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            continue
        merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _segment_for(
    points: tuple[RoutePoint, ...],
    start_time: datetime,
    end_time: datetime,
    kind: JourneyGapKind,
    minimum_gap_s: float,
) -> JourneyGapSegment | None:
    if (end_time - start_time).total_seconds() < minimum_gap_s:
        return None
    within = tuple(point for point in points if start_time <= point.timestamp <= end_time)
    if len(within) < 2:
        # The track does not describe this stretch well enough to narrate it.
        return None
    elevations = [point.elevation_m for point in within if point.elevation_m is not None]
    gain = sum(
        max(0.0, later - earlier)
        for earlier, later in zip(elevations, elevations[1:], strict=False)
    )
    loss = sum(
        max(0.0, earlier - later)
        for earlier, later in zip(elevations, elevations[1:], strict=False)
    )
    return JourneyGapSegment(
        kind=kind,
        start_time=start_time,
        end_time=end_time,
        distance_m=max(0.0, within[-1].distance_from_start_m - within[0].distance_from_start_m),
        elevation_gain_m=gain,
        elevation_loss_m=loss,
    )
