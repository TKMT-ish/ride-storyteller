from datetime import UTC, datetime, timedelta

from app.contracts import GpsEvent, Location, RoutePoint, RouteSummary, VideoQuery
from app.gps import EventThresholds, ParsedRoute, consolidate_events, extract_events


def _point(
    seconds: int,
    latitude: float,
    longitude: float,
    elevation: float,
    distance: float,
    speed: float | None,
) -> RoutePoint:
    return RoutePoint(
        timestamp=datetime(2026, 8, 10, tzinfo=UTC) + timedelta(seconds=seconds),
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation,
        distance_from_start_m=distance,
        speed_mps=speed,
    )


def _route() -> ParsedRoute:
    points = (
        _point(0, -45.0, 168.0, 10, 0, None),
        _point(60, -45.0, 168.01, 45, 800, 13.3),
        _point(120, -44.99, 168.01, 45, 1600, 0.5),
    )
    return ParsedRoute(
        RouteSummary(3, points[0].timestamp, points[-1].timestamp, 1600, 120, 35, 0), points
    )


def test_extracts_departure_arrival_and_elevation_events() -> None:
    events = extract_events(_route(), asset_name_hint="test_ride_001.mp4")
    types = {event.event_type for event in events}
    assert {"departure", "arrival_candidate", "elevation_change"} <= types
    elevation = next(event for event in events if event.event_type == "elevation_change")
    assert elevation.video_query.asset_name_hint == "test_ride_001.mp4"
    assert elevation.importance_hint == 0.70


def test_stop_and_long_ride_thresholds_are_configurable() -> None:
    events = extract_events(
        _route(),
        thresholds=EventThresholds(stop_min_duration_s=30, long_ride_min_duration_s=100),
    )
    types = {event.event_type for event in events}
    assert "stop" in types
    assert "long_ride" in types


def test_consolidates_nearby_volatile_events_but_preserves_other_events() -> None:
    start = datetime(2026, 8, 10, tzinfo=UTC)

    def event(event_id: str, event_type: str, seconds: int, importance: float) -> GpsEvent:
        timestamp = start + timedelta(seconds=seconds)
        return GpsEvent(
            event_id=event_id,
            event_type=event_type,
            start_time=timestamp,
            end_time=timestamp,
            location=Location(-45.0, 168.0),
            importance_hint=importance,
            evidence=(event_type,),
            video_query=VideoQuery("unknown.mp4", 0, 30),
        )

    result = consolidate_events(
        (
            event("departure", "departure", 0, 0.55),
            event("speed-low", "speed_change", 60, 0.50),
            event("speed-high", "speed_change", 600, 0.70),
            event("speed-later", "speed_change", 960, 0.60),
            event("arrival", "arrival_candidate", 1200, 0.75),
        )
    )

    assert [event.event_id for event in result] == [
        "departure",
        "speed-high",
        "speed-later",
        "arrival",
    ]
    representative = result[1]
    assert "consolidated_event_count:2" in representative.evidence


def test_consolidation_keeps_singleton_object_unchanged() -> None:
    start = datetime(2026, 8, 10, tzinfo=UTC)
    singleton = GpsEvent(
        event_id="direction-only",
        event_type="direction_change",
        start_time=start,
        end_time=start,
        location=Location(-45.0, 168.0),
        importance_hint=0.65,
        evidence=("direction_change",),
        video_query=VideoQuery("unknown.mp4", 0, 30),
    )

    result = consolidate_events((singleton,))

    assert result == (singleton,)
    assert result[0] is singleton


def test_consolidation_treats_exact_window_boundary_as_new_cluster() -> None:
    start = datetime(2026, 8, 10, tzinfo=UTC)

    def event(event_id: str, seconds: int) -> GpsEvent:
        timestamp = start + timedelta(seconds=seconds)
        return GpsEvent(
            event_id=event_id,
            event_type="speed_change",
            start_time=timestamp,
            end_time=timestamp,
            location=Location(-45.0, 168.0),
            importance_hint=0.50,
            evidence=("speed_change",),
            video_query=VideoQuery("unknown.mp4", 0, 30),
        )

    result = consolidate_events((event("first", 0), event("boundary", 900)))

    assert [item.event_id for item in result] == ["first", "boundary"]


def test_consolidation_never_merges_different_volatile_event_types() -> None:
    start = datetime(2026, 8, 10, tzinfo=UTC)

    def event(event_id: str, event_type: str) -> GpsEvent:
        return GpsEvent(
            event_id=event_id,
            event_type=event_type,
            start_time=start,
            end_time=start,
            location=Location(-45.0, 168.0),
            importance_hint=0.60,
            evidence=(event_type,),
            video_query=VideoQuery("unknown.mp4", 0, 30),
        )

    result = consolidate_events(
        (event("direction", "direction_change"), event("speed", "speed_change"))
    )

    assert {item.event_id for item in result} == {"direction", "speed"}
