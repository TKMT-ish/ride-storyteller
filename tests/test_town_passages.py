"""Synthetic-track tests for finding where the ride passed through a town."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import RoutePoint
from app.town_passages import (
    TownPassage,
    TownPassageError,
    says_town,
    slow_stretches,
    town_passages,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_STEP_S = 5.0


def _track(
    hours: float,
    *,
    town: tuple[float, float] | None = None,
    towns: tuple[tuple[float, float], ...] = (),
    halt: tuple[float, float] | None = None,
) -> tuple[RoutePoint, ...]:
    """Open road at 25 m/s; in town, 8 m/s with a 20-second stop every 60 seconds."""
    ranges = tuple(towns) + ((town,) if town else ())
    points: list[RoutePoint] = []
    distance = 0.0
    second = 0.0
    while second <= hours * 3600.0:
        speed = 25.0
        if halt and halt[0] <= second <= halt[1]:
            speed = 0.0
        else:
            for start, end in ranges:
                if start <= second <= end:
                    speed = 0.0 if (second - start) % 60.0 < 20.0 else 8.0
                    break
        if points:
            distance += speed * _STEP_S
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=-43.0 - distance / 111_320.0,
                longitude=170.0,
                elevation_m=50.0,
                distance_from_start_m=distance,
                speed_mps=speed,
            )
        )
        second += _STEP_S
    return tuple(points)


def test_street_pace_with_repeated_stops_is_a_slow_stretch() -> None:
    track = _track(2, town=(1800.0, 2400.0))

    found = slow_stretches(track)

    assert len(found) == 1
    start, end = found[0]
    assert abs((start - (_T0 + timedelta(seconds=1800))).total_seconds()) <= 120
    assert abs((end - (_T0 + timedelta(seconds=2400))).total_seconds()) <= 120


def test_open_road_and_a_halt_are_not_town() -> None:
    assert slow_stretches(_track(2)) == ()
    halted = _track(2, halt=(1800.0, 1800.0 + 20 * 60.0))
    assert (
        slow_stretches(
            halted, halts=((_T0 + timedelta(seconds=1800), _T0 + timedelta(seconds=3000)),)
        )
        == ()
    )


def test_a_passage_needs_the_models_word_as_well_as_the_track() -> None:
    track = _track(2, town=(1800.0, 2400.0))
    inside = _T0 + timedelta(seconds=2000)

    assert town_passages(track, {inside: "a rural highway through farmland"}) == ()
    assert town_passages(track, {inside: "a suburban street with shops and a roundabout"}) != ()
    assert town_passages(track, {_T0 + timedelta(seconds=600): "urban street"}) == ()


def test_the_models_town_words_are_recognised() -> None:
    assert says_town("Urban intersection with traffic lights")
    assert says_town("residential street lined with houses")
    assert not says_town("coastal highway with the sea on the left")


def test_a_passage_knows_its_middle_and_refuses_nonsense() -> None:
    passage = TownPassage(_T0, _T0 + timedelta(minutes=4))
    assert passage.middle == _T0 + timedelta(minutes=2)
    assert passage.duration_s == 240.0
    with pytest.raises(TownPassageError):
        TownPassage(_T0, _T0)
    with pytest.raises(TownPassageError):
        slow_stretches(_track(1), min_stops=0)


def test_the_urban_words_are_whole_words_not_substrings() -> None:
    """ "city" inside "electricity", "town" inside "hometown" must not count."""
    assert not says_town("electricity pylons line the highway")
    assert not says_town("a converted barn near the hometown farm")
    assert not says_town("uptown traffic eases past the sign")
    # But the same words on their own, or pluralised, still count.
    assert says_town("a compact city block")
    assert says_town("narrow streets lined with shops")
    assert says_town("through the small towns of the valley")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_s": 0.0},
        {"town_mean_mps": 0.0},
        {"stop_mps": -1.0},
        {"min_stops": 0},
        {"minimum_s": 0.0},
        {"max_gap_s": -1.0},
    ],
)
def test_each_threshold_rejects_its_own_non_positive_edge(kwargs: dict[str, float]) -> None:
    with pytest.raises(TownPassageError):
        slow_stretches(_track(1), **kwargs)


def test_the_thresholds_lowest_valid_values_do_not_raise() -> None:
    # min_stops=1 and stop_mps=0.0/max_gap_s=0.0 are the boundaries themselves,
    # not past them, so they must be accepted rather than rejected.
    assert slow_stretches(_track(1), min_stops=1) == ()
    assert slow_stretches(_track(1), stop_mps=0.0) == ()
    assert slow_stretches(_track(1), max_gap_s=0.0) == ()


def test_fewer_than_two_points_is_never_a_stretch() -> None:
    assert slow_stretches(()) == ()
    single = _track(1)[:1]
    assert slow_stretches(single) == ()


def test_a_passage_exactly_at_the_minimum_length_still_counts() -> None:
    track = _track(2, town=(1800.0, 2400.0))
    start, end = slow_stretches(track)[0]
    duration = (end - start).total_seconds()

    assert slow_stretches(track, minimum_s=duration) != ()
    assert slow_stretches(track, minimum_s=duration + _STEP_S) == ()


def test_a_gap_exactly_at_the_maximum_still_joins_the_passages() -> None:
    # Two towns far enough apart split into two passages at a strict max_gap_s
    # and merge into one once max_gap_s reaches the true gap between them.
    # Rather than compute that gap by formula (the windowed mean-speed check
    # can flicker near the edges), sweep max_gap_s to find where the count
    # actually drops from two passages to one, then check the step boundary.
    track = _track(3, towns=((1800.0, 2400.0), (3600.0, 4200.0)))
    assert len(slow_stretches(track, max_gap_s=1.0)) == 2

    step = int(_STEP_S)
    boundary = next(
        mg for mg in range(step, 2000, step) if len(slow_stretches(track, max_gap_s=float(mg))) == 1
    )

    assert len(slow_stretches(track, max_gap_s=float(boundary - step))) == 2
    assert len(slow_stretches(track, max_gap_s=float(boundary))) == 1


def test_a_hint_exactly_on_the_passages_edge_still_counts() -> None:
    track = _track(2, town=(1800.0, 2400.0))
    start, end = slow_stretches(track)[0]

    assert town_passages(track, {start: "a busy urban street"}) != ()
    assert town_passages(track, {end: "a busy urban street"}) != ()
    just_before = start - timedelta(seconds=_STEP_S)
    assert town_passages(track, {just_before: "a busy urban street"}) == ()
