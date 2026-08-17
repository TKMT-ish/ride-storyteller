from datetime import UTC, datetime

import pytest

from app.contracts import GpsEvent, Location, VideoQuery


def test_valid_gps_event() -> None:
    event = GpsEvent(
        event_id="evt_1",
        event_type="scenery_change",
        start_time=datetime(2026, 8, 10, tzinfo=UTC),
        end_time=datetime(2026, 8, 10, 0, 1, tzinfo=UTC),
        location=Location(0, 0),
        importance_hint=0.5,
        evidence=(),
        video_query=VideoQuery("fixture.mp4", 0, 1),
    )
    assert event.event_id == "evt_1"


def test_invalid_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="importance_hint"):
        GpsEvent(
            event_id="evt_1",
            event_type="scenery_change",
            start_time=datetime(2026, 8, 10, tzinfo=UTC),
            end_time=datetime(2026, 8, 10, 0, 1, tzinfo=UTC),
            location=Location(0, 0),
            importance_hint=1.2,
            evidence=(),
            video_query=VideoQuery("fixture.mp4", 0, 1),
        )
