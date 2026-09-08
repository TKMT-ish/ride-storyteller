"""Synthetic-fixture tests for building the map references. Nothing here goes out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reference_fetch import (
    LANDMARKS_SCHEMA_VERSION,
    PLACES_SCHEMA_VERSION,
    TOURING_ROUTES_SCHEMA_VERSION,
    ReferenceFetchError,
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


def test_an_answer_without_elements_is_refused() -> None:
    with pytest.raises(ReferenceFetchError):
        parse("places", {"version": 0.6}, "NZ")


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
