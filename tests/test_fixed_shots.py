"""Synthetic-fixture tests for the shots a film always carries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.fixed_shots import (
    FAN_STEP_S,
    FIXED_SHOT_STILL_S,
    choose_shots,
    filmed_moments,
    fixed_shot_fan,
    fixed_shot_start,
    fixed_shot_starts,
    fixed_shots_for,
)
from app.gps.moments import Moment, MomentKind

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Window:
    event_id: str
    start_time: datetime


def test_a_departure_window_starts_just_before_the_move() -> None:
    moment = Moment(MomentKind.DEPARTURE, _T0)

    assert fixed_shot_start(moment, 12.0) == _T0 - timedelta(seconds=FIXED_SHOT_STILL_S)


def test_an_arrival_window_ends_just_after_the_stop() -> None:
    moment = Moment(MomentKind.HALT_ARRIVAL, _T0, halt=0)

    start = fixed_shot_start(moment, 12.0)

    assert start + timedelta(seconds=12.0) == _T0 + timedelta(seconds=FIXED_SHOT_STILL_S)


def test_a_window_shorter_than_its_still_part_is_refused() -> None:
    with pytest.raises(ValueError):
        fixed_shot_start(Moment(MomentKind.ARRIVAL, _T0), FIXED_SHOT_STILL_S)


def test_the_starts_come_in_ride_order() -> None:
    moments = (
        Moment(MomentKind.ARRIVAL, _T0 + timedelta(hours=3)),
        Moment(MomentKind.DEPARTURE, _T0),
    )

    starts = fixed_shot_starts(moments, 12.0)

    assert starts == tuple(sorted(starts))
    assert len(starts) == 8  # five windows at the day's start, three at its end


def test_a_window_starting_near_the_moments_window_is_its_shot() -> None:
    departure = Moment(MomentKind.DEPARTURE, _T0)
    arrival = Moment(MomentKind.ARRIVAL, _T0 + timedelta(hours=2))
    windows = (
        _Window("stride", _T0 + timedelta(minutes=5)),
        _Window("leaving", fixed_shot_start(departure, 12.0) + timedelta(seconds=2)),
        _Window("nowhere_near", fixed_shot_start(arrival, 12.0) + timedelta(seconds=40)),
    )

    shots = fixed_shots_for(windows, (departure, arrival), window_s=12.0)

    assert shots == {"leaving": departure}


def test_one_window_is_one_moments_shot_only() -> None:
    """Two moments a second apart cannot both claim the same window."""
    first = Moment(MomentKind.HALT_ARRIVAL, _T0, halt=0)
    second = Moment(MomentKind.HALT_DEPARTURE, _T0 + timedelta(seconds=1), halt=0)
    window = _Window("w", fixed_shot_start(first, 12.0))

    shots = fixed_shots_for((window,), (first, second), window_s=12.0)

    assert list(shots) == ["w"]


def test_a_negative_tolerance_is_refused() -> None:
    with pytest.raises(ValueError):
        fixed_shots_for((), (), window_s=12.0, tolerance_s=-1.0)


def test_a_moment_the_camera_covered_is_kept_as_it_is() -> None:
    departure = Moment(MomentKind.DEPARTURE, _T0)
    recordings = ((_T0 - timedelta(minutes=1), _T0 + timedelta(minutes=10)),)

    assert filmed_moments((departure,), recordings, window_s=12.0) == (departure,)


def test_a_departure_the_camera_missed_becomes_the_first_filmed_moment() -> None:
    """The camera came on twenty minutes after the ride set off (day 3)."""
    departure = Moment(MomentKind.DEPARTURE, _T0)
    came_on = _T0 + timedelta(minutes=20)
    recordings = ((came_on, came_on + timedelta(minutes=10)),)

    (moved,) = filmed_moments((departure,), recordings, window_s=12.0)

    assert moved.kind is MomentKind.DEPARTURE
    assert fixed_shot_start(moved, 12.0) == came_on


def test_an_arrival_the_camera_missed_becomes_the_last_filmed_moment() -> None:
    """The camera went off seven minutes before the ride stopped (day 2)."""
    arrival = Moment(MomentKind.ARRIVAL, _T0 + timedelta(hours=5))
    went_off = _T0 + timedelta(hours=4, minutes=53)
    recordings = ((went_off - timedelta(minutes=10), went_off),)

    (moved,) = filmed_moments((arrival,), recordings, window_s=12.0)

    assert moved.kind is MomentKind.ARRIVAL
    assert fixed_shot_start(moved, 12.0) + timedelta(seconds=12.0) == went_off


def test_a_missed_halt_end_and_a_far_off_camera_are_dropped() -> None:
    halt = Moment(MomentKind.HALT_ARRIVAL, _T0, halt=0)
    arrival = Moment(MomentKind.ARRIVAL, _T0 + timedelta(hours=5))
    recordings = ((_T0 + timedelta(hours=1), _T0 + timedelta(hours=2)),)

    assert filmed_moments((halt, arrival), recordings, window_s=12.0) == ()


def test_a_moment_gets_a_fan_of_windows_later_for_departures_and_earlier_for_arrivals() -> None:
    leaving = Moment(MomentKind.DEPARTURE, _T0)
    arriving = Moment(MomentKind.ARRIVAL, _T0)

    later = fixed_shot_fan(leaving, 12.0)
    earlier = fixed_shot_fan(arriving, 12.0)

    assert later[0] == fixed_shot_start(leaving, 12.0)
    assert later[1] - later[0] == timedelta(seconds=FAN_STEP_S)
    assert earlier[-1] == fixed_shot_start(arriving, 12.0)
    assert earlier[0] < earlier[-1]
    assert (
        len(fixed_shot_starts((leaving, arriving), 12.0)) == 8
    )  # five at the day's start, three at the arrival


def test_the_models_answer_chooses_the_window_that_shows_the_moment() -> None:
    from dataclasses import dataclass

    from app.contracts import VideoAnalysis

    @dataclass(frozen=True)
    class _Judged:
        event_id: str
        start_time: datetime
        analysis: VideoAnalysis | None

    def _seen(stationary: str, event: str) -> VideoAnalysis:
        return VideoAnalysis(
            asset_id="a",
            start_offset_s=0.0,
            end_offset_s=12.0,
            visual_description="x",
            road_type="street",
            scenery_tags=(),
            weather_visible="clear",
            visual_interest_score=0.5,
            story_relevance_score=0.5,
            confidence=0.9,
            analysis_provider="gemini",
            stationary=stationary,
            road_event=event,
        )

    leaving = Moment(MomentKind.DEPARTURE, _T0)
    starts = fixed_shot_fan(leaving, 12.0)
    windows = (
        _Judged("still", starts[0], _seen("yes", "none")),
        _Judged("rolling", starts[1], _seen("no", "setting_off")),
        _Judged("gone", starts[2], _seen("no", "none")),
    )
    fan = fixed_shots_for(windows, (leaving,), window_s=12.0)
    assert set(fan) == {"still", "rolling", "gone"}

    chosen = choose_shots(fan, windows, window_s=12.0)

    assert chosen == {"rolling": leaving}
    # Without the expected event, a moving window beats a still one, and the
    # nearer of two moving ones wins.
    plain = (
        _Judged("still", starts[0], _seen("yes", "none")),
        _Judged("near", starts[1], _seen("no", "none")),
        _Judged("far", starts[2], _seen("no", "none")),
    )
    assert list(
        choose_shots(fixed_shots_for(plain, (leaving,), window_s=12.0), plain, window_s=12.0)
    ) == ["near"]
