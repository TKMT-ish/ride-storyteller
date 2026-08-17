"""Deterministic GPS event extraction for the pre-video prototype."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contracts import GpsEvent, Location, RoutePoint

from .parser import ParsedRoute


@dataclass(frozen=True)
class EventThresholds:
    """Conservative initial thresholds; tune only after inspecting private GPX data."""

    stop_speed_mps: float = 1.0
    stop_min_duration_s: float = 60.0
    long_ride_min_duration_s: float = 900.0
    elevation_change_m: float = 25.0
    speed_change_mps: float = 5.0
    direction_change_degrees: float = 60.0


@dataclass(frozen=True)
class EventConsolidationPolicy:
    """Reduce dense telemetry candidates without discarding the original event list."""

    volatile_event_window_s: float = 900.0
    volatile_event_types: tuple[str, ...] = ("direction_change", "speed_change")

    def __post_init__(self) -> None:
        if self.volatile_event_window_s <= 0:
            raise ValueError("volatile_event_window_s must be positive")


def _bearing_degrees(start: RoutePoint, end: RoutePoint) -> float:
    lat_1 = math.radians(start.latitude)
    lat_2 = math.radians(end.latitude)
    delta_lon = math.radians(end.longitude - start.longitude)
    x = math.sin(delta_lon) * math.cos(lat_2)
    y = math.cos(lat_1) * math.sin(lat_2) - math.sin(lat_1) * math.cos(lat_2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _direction_delta(first: float, second: float) -> float:
    return abs((second - first + 180) % 360 - 180)


def _event(
    event_id: str,
    event_type: str,
    start: RoutePoint,
    end: RoutePoint,
    importance: float,
    evidence: tuple[str, ...],
    asset_name_hint: str,
) -> GpsEvent:
    return GpsEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=start.timestamp,
        end_time=end.timestamp,
        location=Location(end.latitude, end.longitude),
        importance_hint=importance,
        evidence=evidence,
        video_query={
            "asset_name_hint": asset_name_hint,
            "clip_start_offset_s": 0.0,
            "clip_end_offset_s": 30.0,
        },
    )


def extract_events(
    route: ParsedRoute,
    *,
    asset_name_hint: str = "unknown.mp4",
    thresholds: EventThresholds = EventThresholds(),
) -> tuple[GpsEvent, ...]:
    """Extract explainable event candidates without an LLM or map-service lookup."""
    points = route.points
    events = [
        _event(
            "evt_000_departure",
            "departure",
            points[0],
            points[0],
            0.55,
            ("route_start",),
            asset_name_hint,
        )
    ]

    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        elapsed_s = (current.timestamp - previous.timestamp).total_seconds()
        speed_mps = current.speed_mps or 0.0

        if speed_mps <= thresholds.stop_speed_mps and elapsed_s >= thresholds.stop_min_duration_s:
            events.append(
                _event(
                    f"evt_{index:03d}_stop", "stop", previous, current, 0.45,
                    ("low_speed", "duration"), asset_name_hint,
                )
            )

        if previous.elevation_m is not None and current.elevation_m is not None:
            elevation_change = current.elevation_m - previous.elevation_m
            if abs(elevation_change) >= thresholds.elevation_change_m:
                events.append(
                    _event(
                        f"evt_{index:03d}_elevation", "elevation_change", previous, current,
                        0.70, ("elevation_change",), asset_name_hint,
                    )
                )

        speed_delta = abs(speed_mps - previous.speed_mps) if previous.speed_mps is not None else 0.0
        if speed_delta >= thresholds.speed_change_mps:
            events.append(
                _event(
                    f"evt_{index:03d}_speed", "speed_change", previous, current,
                    0.50, ("speed_change",), asset_name_hint,
                )
            )

        if index >= 2:
            before = points[index - 2]
            first_bearing = _bearing_degrees(before, previous)
            second_bearing = _bearing_degrees(previous, current)
            direction_delta = _direction_delta(first_bearing, second_bearing)
            if direction_delta >= thresholds.direction_change_degrees:
                events.append(
                    _event(
                        f"evt_{index:03d}_direction", "direction_change", previous, current,
                        0.65, ("direction_change",), asset_name_hint,
                    )
                )

    if route.summary.duration_s >= thresholds.long_ride_min_duration_s:
        events.append(
            _event(
                "evt_long_ride", "long_ride", points[0], points[-1], 0.60,
                ("duration", "distance"), asset_name_hint,
            )
        )
    events.append(
        _event(
            "evt_arrival_candidate", "arrival_candidate", points[-1], points[-1], 0.75,
            ("route_end",), asset_name_hint,
        )
    )
    return tuple(events)


def consolidate_events(
    events: tuple[GpsEvent, ...],
    *,
    policy: EventConsolidationPolicy = EventConsolidationPolicy(),
) -> tuple[GpsEvent, ...]:
    """Choose one representative within each short volatile-event time window.

    Departure, arrival, stop, elevation and long-ride events are preserved unchanged.
    The caller retains the original output of :func:`extract_events` for audit or
    later threshold tuning.
    """
    stable = [event for event in events if event.event_type not in policy.volatile_event_types]
    volatile_by_type: dict[str, list[GpsEvent]] = {}
    for event in events:
        if event.event_type in policy.volatile_event_types:
            volatile_by_type.setdefault(event.event_type, []).append(event)

    consolidated = list(stable)
    for candidates in volatile_by_type.values():
        consolidated.extend(_consolidate_type(candidates, policy.volatile_event_window_s))
    return tuple(sorted(consolidated, key=lambda event: (event.start_time, event.event_id)))


def _consolidate_type(
    candidates: list[GpsEvent], window_s: float
) -> tuple[GpsEvent, ...]:
    clusters: list[list[GpsEvent]] = []
    for event in sorted(candidates, key=lambda item: (item.start_time, item.event_id)):
        if not clusters:
            clusters.append([event])
            continue
        elapsed_s = (event.start_time - clusters[-1][0].start_time).total_seconds()
        if elapsed_s < window_s:
            clusters[-1].append(event)
        else:
            clusters.append([event])

    return tuple(_representative(cluster) for cluster in clusters)


def _representative(cluster: list[GpsEvent]) -> GpsEvent:
    representative = min(
        cluster, key=lambda event: (-event.importance_hint, event.start_time, event.event_id)
    )
    if len(cluster) == 1:
        return representative
    return GpsEvent(
        event_id=representative.event_id,
        event_type=representative.event_type,
        start_time=representative.start_time,
        end_time=representative.end_time,
        location=representative.location,
        importance_hint=representative.importance_hint,
        evidence=(*representative.evidence, f"consolidated_event_count:{len(cluster)}"),
        video_query=representative.video_query,
    )
