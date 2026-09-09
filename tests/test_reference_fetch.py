"""Synthetic-fixture tests for building the map references. Nothing here goes out."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import reference_fetch
from app.reference_fetch import (
    LANDMARKS_SCHEMA_VERSION,
    PLACES_SCHEMA_VERSION,
    TOURING_ROUTES_SCHEMA_VERSION,
    ReferenceFetchError,
    _post,
    fetch,
    main,
    overpass_query,
    parse,
    read_names,
    write_reference,
)


def _answer(*elements: dict) -> bytes:
    return json.dumps({"version": 0.6, "elements": list(elements)}).encode("utf-8")


# --- the request ---------------------------------------------------------------


def test_the_request_names_a_country_and_a_kind_and_nothing_else() -> None:
    query = overpass_query("places", "NZ")

    assert '"ISO3166-1"="NZ"' in query
    assert "city|town|village" in query
    assert "out;" in query


def test_a_region_that_is_not_a_country_code_is_refused() -> None:
    with pytest.raises(ReferenceFetchError):
        overpass_query("places", "New Zealand")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ReferenceFetchError):
        overpass_query("mountains", "NZ")


def test_the_request_for_passes_and_ferries_names_the_right_tag() -> None:
    passes = overpass_query("passes", "NZ")
    assert 'mountain_pass"="yes"' in passes

    ferries = overpass_query("ferries", "NZ")
    assert 'route"="ferry"' in ferries
    assert "out geom;" in ferries


def test_named_roads_need_names_to_ask_for() -> None:
    with pytest.raises(ReferenceFetchError):
        overpass_query("named-roads", "NZ")

    query = overpass_query("named-roads", "NZ", names=("Summit Road", "High Range Road"))

    assert "Summit\\ Road|High\\ Range\\ Road" in query or "Summit Road" in query


def test_the_names_file_skips_blanks_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "wanted.txt"
    path.write_text("# a comment\n\nSummit Road\nHigh Range Road  # famous\n", encoding="utf-8")

    assert read_names(path) == ("Summit Road", "High Range Road")


def test_a_missing_names_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ReferenceFetchError):
        read_names(tmp_path / "absent.txt")


# --- the answer ----------------------------------------------------------------


def test_towns_are_parsed_and_hamlets_are_left_out() -> None:
    payload = json.loads(
        _answer(
            {"type": "node", "lat": -41.1, "lon": 174.8, "tags": {"place": "town", "name": "A"}},
            {
                "type": "node",
                "lat": -41.2,
                "lon": 174.9,
                "tags": {"place": "city", "name": "B", "population": "215,900"},
            },
            {"type": "node", "lat": -41.3, "lon": 175.0, "tags": {"place": "hamlet", "name": "C"}},
        )
    )

    written = parse("places", payload, "NZ")

    assert written["schema"] == PLACES_SCHEMA_VERSION
    assert [p["name"] for p in written["places"]] == ["A", "B"]
    assert written["places"][1]["population"] == 215900


def test_passes_keep_their_height_when_the_map_gives_one() -> None:
    payload = json.loads(
        _answer(
            {
                "type": "node",
                "lat": -42.0,
                "lon": 171.0,
                "tags": {"name": "High Saddle", "ele": "920"},
            },
            {"type": "node", "lat": -42.1, "lon": 171.1, "tags": {"name": "No Height"}},
        )
    )

    written = parse("passes", payload, "NZ")

    assert written["schema"] == LANDMARKS_SCHEMA_VERSION
    assert written["landmarks"][0]["elevation_m"] == 920.0
    assert written["landmarks"][1]["elevation_m"] is None


def test_an_unparseable_height_is_dropped_not_guessed() -> None:
    payload = json.loads(
        _answer(
            {
                "type": "node",
                "lat": -42.0,
                "lon": 171.0,
                "tags": {"name": "Odd Saddle", "ele": "unknown"},
            }
        )
    )

    written = parse("passes", payload, "NZ")

    assert written["landmarks"][0]["elevation_m"] is None


def test_passes_without_a_name_or_a_position_are_left_out() -> None:
    payload = json.loads(
        _answer(
            {"type": "node", "lat": -42.0, "lon": 171.0, "tags": {}},
            {"type": "node", "tags": {"name": "No Position"}},
            {"type": "node", "lat": -42.0, "lon": 171.0, "tags": {"name": "Real Pass"}},
        )
    )

    written = parse("passes", payload, "NZ")

    assert [p["name"] for p in written["landmarks"]] == ["Real Pass"]


def test_ways_of_one_name_become_one_route_with_all_its_lines() -> None:
    payload = json.loads(
        _answer(
            {
                "type": "way",
                "tags": {"name": "Summit Road"},
                "geometry": [{"lat": -39.0, "lon": 175.8}, {"lat": -39.1, "lon": 175.8}],
            },
            {
                "type": "way",
                "tags": {"name": "Summit Road"},
                "geometry": [{"lat": -39.1, "lon": 175.8}, {"lat": -39.2, "lon": 175.8}],
            },
            {"type": "way", "tags": {"name": "Too Short"}, "geometry": [{"lat": 0.0, "lon": 0.0}]},
        )
    )

    written = parse("named-roads", payload, "NZ")

    assert written["schema"] == TOURING_ROUTES_SCHEMA_VERSION
    assert [r["name"] for r in written["routes"]] == ["Summit Road"]
    assert len(written["routes"][0]["lines"]) == 2


def test_ways_skip_non_ways_and_nodes_without_a_position() -> None:
    payload = json.loads(
        _answer(
            {"type": "node", "tags": {"name": "Not A Way"}},
            {"type": "way", "tags": {}, "geometry": [{"lat": -39.0, "lon": 175.8}]},
            {"type": "way", "tags": {"name": "No Geometry"}},
            {
                "type": "way",
                "tags": {"name": "Odd Nodes"},
                "geometry": [
                    {"lat": -39.0, "lon": 175.8},
                    "not a node",
                    {"lat": None, "lon": 175.8},
                    {"lat": -39.1, "lon": 175.8},
                ],
            },
        )
    )

    written = parse("named-roads", payload, "NZ")

    names = [r["name"] for r in written["routes"]]
    assert names == ["Odd Nodes"]
    assert written["routes"][0]["lines"] == [[[-39.0, 175.8], [-39.1, 175.8]]]


def test_an_answer_without_elements_is_refused() -> None:
    with pytest.raises(ReferenceFetchError):
        parse("places", {"version": 0.6}, "NZ")


def test_parse_refuses_an_unknown_kind() -> None:
    with pytest.raises(ReferenceFetchError):
        parse("mountains", {"elements": []}, "NZ")


# --- asking, and giving up ------------------------------------------------------


def test_the_first_mirror_that_answers_wins() -> None:
    asked: list[str] = []

    def post(url: str, body: bytes) -> bytes:
        asked.append(url)
        if len(asked) == 1:
            raise ReferenceFetchError("the mirror answered 429")
        return _answer()

    payload = fetch("q", endpoints=("one", "two", "three"), post=post)

    assert asked == ["one", "two"]
    assert payload["elements"] == []


def test_when_no_mirror_answers_the_failure_says_so() -> None:
    def post(url: str, body: bytes) -> bytes:
        raise ReferenceFetchError("unreachable")

    with pytest.raises(ReferenceFetchError, match="no mirror answered"):
        fetch("q", endpoints=("one",), post=post)


def test_an_answer_that_is_not_json_is_not_trusted() -> None:
    def post(url: str, body: bytes) -> bytes:
        return b"<html>rate limited</html>"

    with pytest.raises(ReferenceFetchError):
        fetch("q", endpoints=("one",), post=post)


def test_a_json_answer_without_elements_is_not_trusted_either() -> None:
    def post(url: str, body: bytes) -> bytes:
        return b'{"version": 0.6}'

    with pytest.raises(ReferenceFetchError, match="no elements"):
        fetch("q", endpoints=("one",), post=post)


# --- the plain HTTP call, past the fake `post` the tests above use --------------


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def test_post_sends_the_query_and_returns_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        seen["url"] = request.full_url
        seen["header"] = request.get_header("User-agent")
        return _FakeResponse(b'{"elements": []}')

    monkeypatch.setattr(reference_fetch.urllib.request, "urlopen", fake_urlopen)

    assert _post("https://example.invalid/api", b"query") == b'{"elements": []}'
    assert seen["url"] == "https://example.invalid/api"
    assert seen["header"] == reference_fetch.USER_AGENT


def test_post_turns_an_http_error_into_a_reference_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError("https://example.invalid", 429, "rate limited", None, None)

    monkeypatch.setattr(reference_fetch.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ReferenceFetchError, match="429"):
        _post("https://example.invalid/api", b"query")


def test_post_turns_an_unreachable_mirror_into_a_reference_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(reference_fetch.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ReferenceFetchError, match="could not be reached"):
        _post("https://example.invalid/api", b"query")


# --- writing --------------------------------------------------------------------


def test_the_reference_is_written_whole(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nz.json"

    write_reference(path, {"schema": PLACES_SCHEMA_VERSION, "places": []})

    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == PLACES_SCHEMA_VERSION
    assert not (tmp_path / "deep" / "nz.part").exists()


def test_an_unsafe_path_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)

    with pytest.raises(ReferenceFetchError):
        write_reference(link, {})


def test_the_command_reports_a_failure_rather_than_writing_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["named-roads", "--region", "NZ", "--out", str(tmp_path / "x.json")])

    assert code == 1
    assert "reference fetch failed" in capsys.readouterr().err


def test_the_command_writes_the_reference_and_reports_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch(query: str, **_: object) -> dict[str, object]:
        return json.loads(
            _answer(
                {
                    "type": "node",
                    "lat": -41.1,
                    "lon": 174.8,
                    "tags": {"place": "town", "name": "A"},
                }
            )
        )

    monkeypatch.setattr(reference_fetch, "fetch", fake_fetch)
    out = tmp_path / "nz-places.json"

    code = main(["places", "--region", "NZ", "--out", str(out)])

    assert code == 0
    assert "places: 1 entries -> " in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["places"][0]["name"] == "A"
