"""Synthetic-fixture tests for reading towns and passes off the map references."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import RoutePoint
from app.places import (
    LANDMARKS_SCHEMA_VERSION,
    PLACES_SCHEMA_VERSION,
    Landmark,
    PlaceMark,
    PlacePassage,
    PlacesError,
    distance_m,
    landmark_crossings,
    landmarks_or_none,
    load_landmarks,
    load_places,
    passage_at,
    place_passages,
    places_or_none,
    within,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
_DEG_PER_M = 1.0 / 111_320.0


def _track(seconds: float, *, step_s: float = 10.0, mps: float = 20.0) -> tuple[RoutePoint, ...]:
    """A track running due north from the equator at a steady pace."""
    points: list[RoutePoint] = []
    second = 0.0
    while second <= seconds:
        points.append(
            RoutePoint(
                timestamp=_T0 + timedelta(seconds=second),
                latitude=mps * second * _DEG_PER_M,
                longitude=0.0,
                elevation_m=0.0,
                distance_from_start_m=mps * second,
                speed_mps=mps,
            )
        )
        second += step_s
    return tuple(points)


def _waypoints(*offsets_and_norths: tuple[float, float]) -> tuple[RoutePoint, ...]:
    """A track visiting exactly these (seconds-from-T0, metres-north) points, in order."""
    return tuple(
        RoutePoint(
            timestamp=_T0 + timedelta(seconds=second),
            latitude=north_m * _DEG_PER_M,
            longitude=0.0,
            elevation_m=0.0,
            distance_from_start_m=abs(north_m),
            speed_mps=0.0,
        )
        for second, north_m in offsets_and_norths
    )


def _town(name: str, *, kind: str = "town", at_m: float = 0.0, east_m: float = 0.0) -> PlaceMark:
    return PlaceMark(
        name=name,
        kind=kind,
        population=1000,
        latitude=at_m * _DEG_PER_M,
        longitude=east_m * _DEG_PER_M,
    )


# --- the references -----------------------------------------------------------


def test_a_reference_of_another_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "nz.json").write_text(
        json.dumps({"schema": "places-v99", "places": []}), encoding="utf-8"
    )

    assert places_or_none(tmp_path) == ()


def test_places_and_landmarks_are_read_from_a_directory(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "schema": PLACES_SCHEMA_VERSION,
                "places": [
                    {
                        "name": "Riverton",
                        "kind": "town",
                        "population": 2000,
                        "latitude": 1.0,
                        "longitude": 2.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "schema": LANDMARKS_SCHEMA_VERSION,
                "landmarks": [
                    {
                        "name": "High Saddle",
                        "kind": "pass",
                        "latitude": 3.0,
                        "longitude": 4.0,
                        "elevation_m": 920.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert [p.name for p in places_or_none(tmp_path)] == ["Riverton"]
    assert [m.elevation_m for m in landmarks_or_none(tmp_path)] == [920.0]


def test_a_place_of_an_unknown_kind_is_refused() -> None:
    with pytest.raises(PlacesError):
        PlaceMark(name="Somewhere", kind="hamlet", population=None, latitude=0.0, longitude=0.0)


def test_a_place_with_a_blank_name_is_refused() -> None:
    with pytest.raises(PlacesError):
        PlaceMark(name="   ", kind="town", population=None, latitude=0.0, longitude=0.0)


def test_a_landmark_with_a_blank_name_or_kind_is_refused() -> None:
    with pytest.raises(PlacesError):
        Landmark(name=" ", kind="pass", latitude=0.0, longitude=0.0)
    with pytest.raises(PlacesError):
        Landmark(name="High Saddle", kind=" ", latitude=0.0, longitude=0.0)


# --- reading errors -------------------------------------------------------------


def test_a_missing_reference_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PlacesError):
        load_places(tmp_path / "missing.json")


def test_a_symlinked_reference_file_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"schema": PLACES_SCHEMA_VERSION, "places": []}), encoding="utf-8")
    link = tmp_path / "link.json"
    os.symlink(real, link)

    with pytest.raises(PlacesError):
        load_places(link)


def test_malformed_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(PlacesError):
        load_places(path)


def test_a_payload_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(PlacesError):
        load_places(path)


def test_a_place_item_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad-item.json"
    path.write_text(
        json.dumps({"schema": PLACES_SCHEMA_VERSION, "places": ["Riverton"]}), encoding="utf-8"
    )

    with pytest.raises(PlacesError):
        load_places(path)


def test_a_place_item_missing_a_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "missing-key.json"
    path.write_text(
        json.dumps(
            {"schema": PLACES_SCHEMA_VERSION, "places": [{"name": "Riverton", "kind": "town"}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(PlacesError):
        load_places(path)


def test_a_place_item_with_a_bad_coordinate_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad-coordinate.json"
    path.write_text(
        json.dumps(
            {
                "schema": PLACES_SCHEMA_VERSION,
                "places": [
                    {
                        "name": "Riverton",
                        "kind": "town",
                        "population": None,
                        "latitude": "north",
                        "longitude": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PlacesError):
        load_places(path)


def test_a_landmark_item_missing_a_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "missing-key.json"
    path.write_text(
        json.dumps({"schema": LANDMARKS_SCHEMA_VERSION, "landmarks": [{"name": "High Saddle"}]}),
        encoding="utf-8",
    )

    with pytest.raises(PlacesError):
        load_landmarks(path)


def test_a_landmark_item_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad-item.json"
    path.write_text(
        json.dumps({"schema": LANDMARKS_SCHEMA_VERSION, "landmarks": ["High Saddle"]}),
        encoding="utf-8",
    )

    with pytest.raises(PlacesError):
        load_landmarks(path)


def test_a_missing_directory_has_no_places_or_landmarks(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert places_or_none(missing) == ()
    assert landmarks_or_none(missing) == ()


def test_a_symlinked_directory_has_no_places(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)

    assert places_or_none(link) == ()


def test_a_non_json_file_in_the_directory_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not a reference", encoding="utf-8")

    assert places_or_none(tmp_path) == ()


def test_one_malformed_file_does_not_hide_a_valid_one(tmp_path: Path) -> None:
    (tmp_path / "a-broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "b-good.json").write_text(
        json.dumps(
            {
                "schema": PLACES_SCHEMA_VERSION,
                "places": [
                    {
                        "name": "Riverton",
                        "kind": "town",
                        "population": None,
                        "latitude": 1.0,
                        "longitude": 2.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert [p.name for p in places_or_none(tmp_path)] == ["Riverton"]


# --- passing through ----------------------------------------------------------


def test_the_ride_came_through_a_town_it_passed_within_reach_of() -> None:
    """The owner's day-10 note (2026-09-07): a city the ride passed must be said,
    even though a ring road never slows the ride down."""
    points = _track(600.0)  # 12 km north in ten minutes
    near = _town("Nearby", at_m=6000.0, east_m=900.0)
    far = _town("Farther", at_m=6000.0, east_m=4000.0)

    passages = place_passages(points, (near, far))

    assert [p.name for p in passages] == ["Nearby"]
    assert passages[0].start_time >= _T0
    assert passages[0].end_time > passages[0].start_time


def test_a_city_reaches_further_than_a_village() -> None:
    points = _track(600.0)
    city = _town("Big", kind="city", at_m=6000.0, east_m=2000.0)
    village = _town("Small", kind="village", at_m=6000.0, east_m=2000.0)

    assert [p.name for p in place_passages(points, (city, village))] == ["Big"]


def test_two_visits_close_together_are_one_passage() -> None:
    points = _track(600.0)
    place = _town("Middle", kind="city", at_m=6000.0, east_m=0.0)

    passages = place_passages(points, (place,), merge_gap_s=10 * 60.0)

    assert len(passages) == 1


def test_the_largest_place_is_the_one_the_ride_is_in() -> None:
    points = _track(600.0)
    city = _town("Big", kind="city", at_m=6000.0)
    village = _town("Suburb", kind="village", at_m=6000.0)

    passages = place_passages(points, (city, village))
    inside = passage_at(passages, _T0 + timedelta(seconds=300))

    assert inside is not None and inside.name == "Big"


def test_a_radius_wider_than_the_index_is_refused() -> None:
    with pytest.raises(PlacesError):
        place_passages(_track(60.0), (), radius_m={"city": 100_000.0})


def test_nothing_to_match_against_is_no_passage() -> None:
    assert place_passages(_track(60.0), ()) == ()


def test_a_negative_merge_gap_is_refused() -> None:
    with pytest.raises(PlacesError):
        place_passages(_track(60.0), (), merge_gap_s=-1.0)


def test_a_non_positive_radius_is_refused() -> None:
    with pytest.raises(PlacesError):
        place_passages(_track(60.0), (), radius_m={"town": 0.0})


def test_overlapping_places_are_both_reported() -> None:
    """A suburb inside a city is still its own passage; the caller picks which to say."""
    points = _track(600.0)
    city = _town("Big", kind="city", at_m=6000.0)
    suburb = _town("Suburb", kind="village", at_m=6000.0)

    passages = place_passages(points, (city, suburb))

    assert sorted(p.name for p in passages) == ["Big", "Suburb"]


def test_a_place_left_and_returned_to_after_the_merge_gap_is_two_passages() -> None:
    """A visit, a long ride away, then a second visit: two separate passages."""
    place = _town("Middle", kind="city", at_m=6000.0)
    points = _waypoints(
        (0.0, 6000.0),  # inside
        (10.0, 6000.0),  # inside
        (1000.0, 50_000.0),  # far away, well past the merge gap
        (1010.0, 6000.0),  # inside again
        (1020.0, 6000.0),  # inside
    )

    passages = place_passages(points, (place,), merge_gap_s=30.0)

    assert len(passages) == 2


def test_a_return_within_the_merge_gap_is_still_one_passage() -> None:
    """A visit, a brief detour outside the radius, then straight back in: one passage."""
    place = _town("Middle", kind="city", at_m=6000.0)
    points = _waypoints(
        (0.0, 6000.0),  # inside
        (10.0, 6000.0),  # inside
        (20.0, 50_000.0),  # outside, briefly
        (30.0, 6000.0),  # inside again, within the merge gap
    )

    passages = place_passages(points, (place,), merge_gap_s=60.0)

    assert len(passages) == 1


def test_a_passage_cannot_end_before_it_starts() -> None:
    with pytest.raises(PlacesError):
        PlacePassage(
            name="Riverton",
            kind="town",
            population=None,
            start_time=_T0,
            end_time=_T0 - timedelta(seconds=1),
            nearest_m=0.0,
        )


def test_a_passages_middle_is_halfway_between_its_ends() -> None:
    passage = PlacePassage(
        name="Riverton",
        kind="town",
        population=None,
        start_time=_T0,
        end_time=_T0 + timedelta(seconds=600),
        nearest_m=0.0,
    )

    assert passage.middle == _T0 + timedelta(seconds=300)


def test_no_place_covers_the_moment_asked_about() -> None:
    passage = PlacePassage(
        name="Riverton",
        kind="town",
        population=None,
        start_time=_T0,
        end_time=_T0 + timedelta(seconds=60),
        nearest_m=0.0,
    )

    assert passage_at((passage,), _T0 + timedelta(hours=1)) is None


def test_a_tie_between_same_kind_places_favours_the_bigger_population() -> None:
    small = PlacePassage(
        name="Small",
        kind="town",
        population=200,
        start_time=_T0,
        end_time=_T0 + timedelta(seconds=60),
        nearest_m=0.0,
    )
    big = PlacePassage(
        name="Big",
        kind="town",
        population=5000,
        start_time=_T0,
        end_time=_T0 + timedelta(seconds=60),
        nearest_m=0.0,
    )

    assert passage_at((small, big), _T0).name == "Big"


# --- passes -------------------------------------------------------------------


def test_a_pass_the_track_crossed_is_reported_at_its_nearest_moment() -> None:
    points = _track(600.0)
    summit = Landmark(name="High Saddle", kind="pass", latitude=6000.0 * _DEG_PER_M, longitude=0.0)
    aside = Landmark(name="Other", kind="pass", latitude=6000.0 * _DEG_PER_M, longitude=0.01)

    crossings = landmark_crossings(points, (summit, aside))

    assert [c.name for c in crossings] == ["High Saddle"]
    assert crossings[0].nearest_m < 10.0
    assert crossings[0].at == _T0 + timedelta(seconds=300)


def test_a_reach_wider_than_the_index_is_refused() -> None:
    with pytest.raises(PlacesError):
        landmark_crossings(_track(60.0), (), within_m=100_000.0)


def test_a_non_positive_reach_is_refused() -> None:
    with pytest.raises(PlacesError):
        landmark_crossings(_track(60.0), (), within_m=0.0)


def test_a_landmark_is_reported_at_its_single_closest_point_of_several() -> None:
    """Several points come within reach; the crossing is at the nearest of them."""
    summit = Landmark(name="High Saddle", kind="pass", latitude=6000.0 * _DEG_PER_M, longitude=0.0)
    points = _waypoints(
        (0.0, 5800.0),  # within reach, 200m off
        (10.0, 6000.0),  # within reach, right on top
        (20.0, 5850.0),  # within reach, 150m off
    )

    crossings = landmark_crossings(points, (summit,), within_m=300.0)

    assert len(crossings) == 1
    assert crossings[0].nearest_m < 1.0
    assert crossings[0].at == _T0 + timedelta(seconds=10)


def test_the_distance_is_measured_in_metres() -> None:
    assert 110_000 < distance_m(0.0, 0.0, 1.0, 0.0) < 112_000
    assert distance_m(0.0, 0.0, 0.0, 0.0) == 0.0


# --- whether the track was there ------------------------------------------------


def test_a_point_within_slack_of_the_moment_is_there() -> None:
    points = _track(60.0, step_s=10.0)

    assert within(points, _T0 + timedelta(seconds=25), timedelta(seconds=5))


def test_a_point_outside_slack_of_the_moment_is_not_there() -> None:
    points = _track(60.0, step_s=10.0)

    assert not within(points, _T0 + timedelta(seconds=25), timedelta(seconds=2))


def test_exactly_on_the_edge_of_the_slack_counts_as_there() -> None:
    points = _track(60.0, step_s=10.0)

    assert within(points, _T0 + timedelta(seconds=13), timedelta(seconds=3))


def test_an_empty_track_is_never_there() -> None:
    assert not within((), _T0, timedelta(seconds=5))


def test_a_moment_before_the_first_point_uses_the_first_point() -> None:
    points = _track(60.0, step_s=10.0)

    assert within(points, _T0 - timedelta(seconds=2), timedelta(seconds=5))
    assert not within(points, _T0 - timedelta(seconds=10), timedelta(seconds=5))


def test_a_moment_after_the_last_point_uses_the_last_point() -> None:
    points = _track(60.0, step_s=10.0)
    last = points[-1].timestamp

    assert within(points, last + timedelta(seconds=2), timedelta(seconds=5))
    assert not within(points, last + timedelta(seconds=10), timedelta(seconds=5))
