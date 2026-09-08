from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import GpsEvent, Location, RoutePoint, RouteSummary, VideoQuery
from app.gps import (
    EventConsolidationPolicy,
    EventThresholds,
    ParsedRoute,
    consolidate_events,
    extract_events,
)
from app.gps.events import _direction_delta


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


# ---------------------------------------------------------------------------
# Boundary and failure-path tests
# ---------------------------------------------------------------------------


def _ts(seconds: float) -> datetime:
    return datetime(2026, 8, 10, tzinfo=UTC) + timedelta(seconds=seconds)


def _route_of(points: tuple[RoutePoint, ...], *, duration_s: float = 0.0) -> ParsedRoute:
    return ParsedRoute(
        RouteSummary(
            len(points),
            points[0].timestamp,
            points[-1].timestamp,
            points[-1].distance_from_start_m,
            duration_s,
            0,
            0,
        ),
        points,
    )


def _event_types(events: tuple[GpsEvent, ...]) -> set[str]:
    return {event.event_type for event in events}


def test_stop_boundary_speed_and_duration_both_inclusive() -> None:
    """stop_speed_mps (<=) and stop_min_duration_s (>=) both trigger exactly at threshold."""
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 0, 1.0),
    )
    events = extract_events(_route_of(points))
    assert "stop" in _event_types(events)


def test_stop_absent_when_speed_just_above_threshold() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 0, 1.0001),
    )
    events = extract_events(_route_of(points))
    assert "stop" not in _event_types(events)


def test_stop_absent_when_duration_just_below_threshold() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(59.999), -45.0, 168.0, None, 0, 0.5),
    )
    events = extract_events(_route_of(points))
    assert "stop" not in _event_types(events)


def test_elevation_change_boundary_inclusive_both_directions() -> None:
    """elevation_change_m threshold (>=) triggers exactly at 25m, gain or loss."""
    gain = (
        RoutePoint(_ts(0), -45.0, 168.0, 100.0, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, 125.0, 100, 1.6),
    )
    loss = (
        RoutePoint(_ts(0), -45.0, 168.0, 125.0, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, 100.0, 100, 1.6),
    )
    assert "elevation_change" in _event_types(extract_events(_route_of(gain)))
    assert "elevation_change" in _event_types(extract_events(_route_of(loss)))


def test_elevation_change_absent_just_below_threshold() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, 100.0, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, 124.999, 100, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "elevation_change" not in _event_types(events)


def test_elevation_change_skipped_without_exception_when_previous_elevation_none() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, 500.0, 100, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "elevation_change" not in _event_types(events)


def test_elevation_change_skipped_without_exception_when_current_elevation_none() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, 500.0, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "elevation_change" not in _event_types(events)


def test_speed_change_boundary_inclusive() -> None:
    """speed_change_mps threshold (>=) triggers exactly at a 5.0 m/s delta."""
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, 10.0),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 15.0),
    )
    events = extract_events(_route_of(points))
    assert "speed_change" in _event_types(events)


def test_speed_change_absent_just_below_threshold() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, 10.0),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 14.999),
    )
    events = extract_events(_route_of(points))
    assert "speed_change" not in _event_types(events)


def test_speed_change_delta_forced_zero_when_previous_speed_is_none() -> None:
    """A None previous speed makes speed_delta 0.0, even with a huge current speed."""
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 40.0),
    )
    events = extract_events(_route_of(points))
    assert "speed_change" not in _event_types(events)


def test_direction_delta_exact_threshold_boundary() -> None:
    assert _direction_delta(0.0, 60.0) == 60.0
    assert _direction_delta(0.0, 59.999) < 60.0


def test_direction_delta_handles_wraparound_both_ways() -> None:
    """Bearings crossing the 0/360 seam must report the short way around."""
    assert _direction_delta(10.0, 350.0) == pytest.approx(20.0)
    assert _direction_delta(0.0, 300.0) == pytest.approx(60.0)
    assert _direction_delta(0.0, 180.0) == pytest.approx(180.0)


def test_direction_change_requires_at_least_three_points() -> None:
    """A 2-point route never reaches the index >= 2 window, regardless of turn severity."""
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -44.99, 168.0, None, 100, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "direction_change" not in _event_types(events)


def test_direction_change_detected_for_a_real_turn() -> None:
    """Heading north then east is roughly a 90-degree turn, well past the 60-degree threshold."""
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -44.99, 168.0, None, 100, 1.6),
        RoutePoint(_ts(120), -44.99, 168.02, None, 200, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "direction_change" in _event_types(events)


def test_direction_change_absent_on_a_straight_line() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -44.99, 168.0, None, 100, 1.6),
        RoutePoint(_ts(120), -44.98, 168.0, None, 200, 1.6),
    )
    events = extract_events(_route_of(points))
    assert "direction_change" not in _event_types(events)


def test_long_ride_boundary_inclusive() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 1.6),
    )
    events = extract_events(_route_of(points, duration_s=900.0))
    assert "long_ride" in _event_types(events)


def test_long_ride_absent_just_below_threshold() -> None:
    points = (
        RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),
        RoutePoint(_ts(60), -45.0, 168.0, None, 100, 1.6),
    )
    events = extract_events(_route_of(points, duration_s=899.999))
    assert "long_ride" not in _event_types(events)


def test_extract_events_single_point_route_yields_only_departure_and_arrival() -> None:
    """The for-loop range(1, 1) never executes; no exception, no other event types."""
    points = (RoutePoint(_ts(0), -45.0, 168.0, None, 0, None),)
    events = extract_events(_route_of(points))
    assert _event_types(events) == {"departure", "arrival_candidate"}
    assert len(events) == 2


def test_consolidate_events_empty_input_returns_empty_tuple() -> None:
    assert consolidate_events(()) == ()


def test_event_consolidation_policy_rejects_zero_and_negative_window() -> None:
    with pytest.raises(ValueError, match="volatile_event_window_s must be positive"):
        EventConsolidationPolicy(volatile_event_window_s=0)
    with pytest.raises(ValueError, match="volatile_event_window_s must be positive"):
        EventConsolidationPolicy(volatile_event_window_s=-1.0)


def test_event_consolidation_policy_accepts_a_tiny_positive_window() -> None:
    policy = EventConsolidationPolicy(volatile_event_window_s=0.001)
    assert policy.volatile_event_window_s == 0.001


def test_representative_tiebreak_prefers_lexicographically_smaller_event_id() -> None:
    """Equal importance and equal start_time fall through to event_id as the final tiebreak."""
    start = datetime(2026, 8, 10, tzinfo=UTC)

    def event(event_id: str) -> GpsEvent:
        return GpsEvent(
            event_id=event_id,
            event_type="speed_change",
            start_time=start,
            end_time=start,
            location=Location(-45.0, 168.0),
            importance_hint=0.50,
            evidence=("speed_change",),
            video_query=VideoQuery("unknown.mp4", 0, 30),
        )

    result = consolidate_events((event("zzz"), event("aaa")))

    assert len(result) == 1
    assert result[0].event_id == "aaa"
    assert "consolidated_event_count:2" in result[0].evidence


def test_stable_event_types_are_never_consolidated_even_when_adjacent_in_time() -> None:
    """Only volatile_event_types are clustered; stop/elevation/etc. pass through untouched."""
    start = datetime(2026, 8, 10, tzinfo=UTC)

    def stop_event(event_id: str, seconds: int) -> GpsEvent:
        timestamp = start + timedelta(seconds=seconds)
        return GpsEvent(
            event_id=event_id,
            event_type="stop",
            start_time=timestamp,
            end_time=timestamp,
            location=Location(-45.0, 168.0),
            importance_hint=0.45,
            evidence=("low_speed", "duration"),
            video_query=VideoQuery("unknown.mp4", 0, 30),
        )

    result = consolidate_events((stop_event("stop-1", 0), stop_event("stop-2", 1)))

    assert {event.event_id for event in result} == {"stop-1", "stop-2"}
