"""Synthetic-fixture tests for naming where the ride went from and to."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.contracts import RoutePoint
from app.place_names import (
    NOTHING,
    PLACE_NAMES_FILE_NAME,
    PlaceName,
    PlaceNames,
    PlaceNamesError,
    _fetch,
    geocoding_url,
    leg_names,
    maps_key,
    parse_geocoding,
    point_at,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _answer(*components: tuple[str, list[str]], status: str = "OK") -> bytes:
    return json.dumps(
        {
            "status": status,
            "results": [
                {
                    "address_components": [
                        {"long_name": name, "short_name": name, "types": types}
                        for name, types in components
                    ]
                }
            ],
        }
    ).encode("utf-8")


def _fake_fetch(answers: dict[str, bytes], seen: list[str]):
    def fetch(url: str) -> bytes:
        seen.append(url)
        latlng = parse_qs(urlparse(url).query)["latlng"][0]
        return answers[latlng]

    return fetch


def test_the_request_carries_one_rounded_coordinate_and_nothing_else() -> None:
    url = geocoding_url(-43.123456, 170.987654, key="k", language="ja")

    query = parse_qs(urlparse(url).query)
    assert query["latlng"] == ["-43.1235,170.9877"]
    assert query["language"] == ["ja"]
    assert set(query) == {"latlng", "language", "key"}


def test_the_most_local_place_and_the_road_are_read_from_the_answer() -> None:
    payload = json.loads(
        _answer(
            ("State Highway 6", ["route"]),
            ("Millbrook", ["locality", "political"]),
            ("Westland District", ["administrative_area_level_2", "political"]),
        )
    )

    assert parse_geocoding(payload) == PlaceName(place="Millbrook", road="State Highway 6")


def test_a_district_names_the_point_when_no_town_does() -> None:
    payload = json.loads(
        _answer(
            ("Unnamed Road", ["route"]), ("Mackenzie District", ["administrative_area_level_2"])
        )
    )

    assert parse_geocoding(payload) == PlaceName(place="Mackenzie District", road=None)


def test_no_result_is_no_name_and_a_refusal_is_an_error() -> None:
    assert parse_geocoding({"status": "ZERO_RESULTS", "results": []}) == NOTHING
    with pytest.raises(PlaceNamesError):
        parse_geocoding({"status": "REQUEST_DENIED", "results": []})


def test_names_are_asked_once_and_kept_in_the_package(tmp_path: Path) -> None:
    seen: list[str] = []
    answers = {"-43.0000,170.0000": _answer(("Sandport", ["locality"]))}
    names = PlaceNames(tmp_path, key="k", fetch=_fake_fetch(answers, seen))

    first = names.name_at(-43.00001, 170.00004)
    again = names.name_at(-43.0, 170.0)

    assert first == again == PlaceName(place="Sandport", road=None)
    assert len(seen) == 1
    written = json.loads((tmp_path / PLACE_NAMES_FILE_NAME).read_text(encoding="utf-8"))
    assert written["names"]["-43.0000,170.0000@ja"] == {
        "place": "Sandport",
        "road": None,
        "suburb": None,
        "spot": None,
    }

    reopened = PlaceNames(tmp_path, key="k", fetch=_fake_fetch({}, seen))
    assert reopened.name_at(-43.0, 170.0) == first
    assert len(seen) == 1


def test_without_a_key_nothing_is_asked(tmp_path: Path) -> None:
    names = PlaceNames(tmp_path, key="", fetch=_fake_fetch({}, []))

    with pytest.raises(PlaceNamesError, match="key"):
        names.name_at(-43.0, 170.0)


def test_leg_names_take_the_track_point_nearest_each_end(tmp_path: Path) -> None:
    points = tuple(
        RoutePoint(
            timestamp=_T0 + timedelta(minutes=m),
            latitude=-43.0 - m * 0.01,
            longitude=170.0,
            elevation_m=None,
            distance_from_start_m=m * 1000.0,
            speed_mps=None,
        )
        for m in range(0, 61, 10)
    )
    answers = {
        "-43.0000,170.0000": _answer(("A", ["locality"])),
        "-43.6000,170.0000": _answer(("B", ["locality"])),
    }
    names = PlaceNames(tmp_path, key="k", fetch=_fake_fetch(answers, []))

    pairs = leg_names(names, points, [(_T0, _T0 + timedelta(hours=1))])

    assert pairs == [(PlaceName("A", None), PlaceName("B", None))]


def test_leg_names_shares_the_cache_across_spans(tmp_path: Path) -> None:
    """A point that ends one leg and starts the next is asked only once."""
    points = tuple(
        RoutePoint(
            timestamp=_T0 + timedelta(minutes=m),
            latitude=-43.0 - m * 0.01,
            longitude=170.0,
            elevation_m=None,
            distance_from_start_m=m * 1000.0,
            speed_mps=None,
        )
        for m in range(0, 61, 10)
    )
    answers = {
        "-43.0000,170.0000": _answer(("A", ["locality"])),
        "-43.3000,170.0000": _answer(("B", ["locality"])),
        "-43.6000,170.0000": _answer(("C", ["locality"])),
    }
    seen: list[str] = []
    names = PlaceNames(tmp_path, key="k", fetch=_fake_fetch(answers, seen))

    pairs = leg_names(
        names,
        points,
        [
            (_T0, _T0 + timedelta(minutes=30)),
            (_T0 + timedelta(minutes=30), _T0 + timedelta(minutes=60)),
        ],
    )

    assert pairs == [
        (PlaceName("A", None), PlaceName("B", None)),
        (PlaceName("B", None), PlaceName("C", None)),
    ]
    assert len(seen) == 3  # the shared midpoint is asked once, not twice


def test_point_at_refuses_an_empty_track() -> None:
    with pytest.raises(PlaceNamesError):
        point_at([], _T0)


def test_parse_geocoding_refuses_results_that_are_not_a_list() -> None:
    with pytest.raises(PlaceNamesError):
        parse_geocoding({"status": "OK", "results": "not-a-list"})


def test_parse_geocoding_skips_malformed_entries_and_still_finds_a_name() -> None:
    payload = {
        "status": "OK",
        "results": [
            "not-a-mapping",
            {"address_components": "not-a-list"},
            {
                "address_components": [
                    "not-a-mapping",
                    {"long_name": 123, "types": ["locality"]},
                    {"long_name": "", "types": ["locality"]},
                    {"long_name": "Real Town", "types": "not-a-list"},
                    {"long_name": "Real Town", "types": ["locality"]},
                ]
            },
        ],
    }

    assert parse_geocoding(payload) == PlaceName(place="Real Town", road=None)


def test_parse_geocoding_prefers_the_most_local_type() -> None:
    payload = json.loads(
        _answer(
            ("Some District", ["administrative_area_level_2"]),
            ("Some Postal Town", ["postal_town"]),
            ("Some Locality", ["locality"]),
        )
    )

    assert parse_geocoding(payload) == PlaceName(place="Some Locality", road=None)


def test_parse_geocoding_reads_a_natural_feature() -> None:
    payload = json.loads(_answer(("Milford Sound", ["natural_feature"])))

    assert parse_geocoding(payload) == PlaceName(place="Milford Sound", road=None)


def test_a_symlinked_package_path_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    (tmp_path / PLACE_NAMES_FILE_NAME).symlink_to(target)

    with pytest.raises(PlaceNamesError, match="unsafe"):
        PlaceNames(tmp_path, key="k", fetch=_fake_fetch({}, []))


def test_a_corrupted_package_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / PLACE_NAMES_FILE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(PlaceNamesError):
        PlaceNames(tmp_path, key="k", fetch=_fake_fetch({}, []))


def test_an_unsupported_schema_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / PLACE_NAMES_FILE_NAME).write_text(
        json.dumps({"schema_version": "place-names-v0", "names": {}}), encoding="utf-8"
    )

    with pytest.raises(PlaceNamesError, match="schema"):
        PlaceNames(tmp_path, key="k", fetch=_fake_fetch({}, []))


def test_a_names_payload_that_is_not_a_dict_is_ignored(tmp_path: Path) -> None:
    """A malformed `names` block is treated as empty, not fatal -- no film waits on a name."""
    (tmp_path / PLACE_NAMES_FILE_NAME).write_text(
        json.dumps({"schema_version": "place-names-v1", "names": ["oops"]}), encoding="utf-8"
    )
    answers = {"-43.0000,170.0000": _answer(("Sandport", ["locality"]))}
    names = PlaceNames(tmp_path, key="k", fetch=_fake_fetch(answers, []))

    assert names.name_at(-43.0, 170.0) == PlaceName(place="Sandport", road=None)


def test_a_failed_fetch_is_never_cached(tmp_path: Path) -> None:
    """A point the service refused must be asked again next time, not remembered as failed."""
    calls = 0

    def failing_fetch(url: str) -> bytes:
        nonlocal calls
        calls += 1
        raise PlaceNamesError("the place service could not be reached")

    names = PlaceNames(tmp_path, key="k", fetch=failing_fetch)

    with pytest.raises(PlaceNamesError):
        names.name_at(-43.0, 170.0)
    with pytest.raises(PlaceNamesError):
        names.name_at(-43.0, 170.0)

    assert calls == 2
    assert names.asked == 0


def test_a_non_json_response_is_reported(tmp_path: Path) -> None:
    names = PlaceNames(tmp_path, key="k", fetch=lambda url: b"not json")

    with pytest.raises(PlaceNamesError):
        names.name_at(-43.0, 170.0)


def test_a_response_that_is_not_valid_utf8_is_reported(tmp_path: Path) -> None:
    names = PlaceNames(tmp_path, key="k", fetch=lambda url: b"\xff\xfe")

    with pytest.raises(PlaceNamesError):
        names.name_at(-43.0, 170.0)


def test_a_response_that_is_not_a_json_object_is_reported(tmp_path: Path) -> None:
    names = PlaceNames(tmp_path, key="k", fetch=lambda url: b"[]")

    with pytest.raises(PlaceNamesError):
        names.name_at(-43.0, 170.0)


def test_a_key_of_none_falls_back_to_the_configured_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "configured-key")
    seen: list[str] = []
    answers = {"-43.0000,170.0000": _answer(("Sandport", ["locality"]))}
    names = PlaceNames(tmp_path, key=None, fetch=_fake_fetch(answers, seen))

    names.name_at(-43.0, 170.0)

    assert parse_qs(urlparse(seen[0]).query)["key"] == ["configured-key"]


def test_maps_key_prefers_the_environment_over_the_local_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "  from-env  ")
    monkeypatch.setattr(
        "app.place_names.load_local_environment",
        lambda: {"GOOGLE_MAPS_API_KEY": "from-file"},
    )

    assert maps_key() == "from-env"


def test_maps_key_falls_back_to_the_local_environment_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.place_names.load_local_environment",
        lambda: {"GOOGLE_MAPS_API_KEY": "from-file"},
    )

    assert maps_key() == "from-file"


def test_maps_key_is_empty_when_nothing_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr("app.place_names.load_local_environment", lambda: {})

    assert maps_key() == ""


def test_fetch_reports_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(url: str, timeout: int = 20):
        raise urllib.error.HTTPError(url, 403, "denied", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_http_error)

    with pytest.raises(PlaceNamesError, match="403"):
        _fetch("https://maps.googleapis.com/maps/api/geocode/json")


def test_fetch_reports_an_unreachable_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(url: str, timeout: int = 20):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)

    with pytest.raises(PlaceNamesError, match="could not be reached"):
        _fetch("https://maps.googleapis.com/maps/api/geocode/json")


def test_fetch_returns_the_bytes_of_a_reachable_service(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            return b'{"status": "ZERO_RESULTS", "results": []}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=20: _FakeResponse())

    assert _fetch("https://maps.googleapis.com/maps/api/geocode/json") == (
        b'{"status": "ZERO_RESULTS", "results": []}'
    )
