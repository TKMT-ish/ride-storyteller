"""Synthetic-fixture tests for the trip's day number and the local clock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.trip_days import _first_time, day_label, local_offset_s, package_date, trip_day


def _package(root: Path, name: str, first_time: str, *, camera_offset_s: float = -46_800.0) -> Path:
    package = root / name
    package.mkdir()
    gpx = package / "track.gpx"
    gpx.write_text(
        '<?xml version="1.0"?>\n<gpx version="1.1"><trk><trkseg>'
        f'<trkpt lat="-43" lon="170"><time>{first_time}</time></trkpt>'
        "</trkseg></trk></gpx>\n",
        encoding="utf-8",
    )
    (package / "local-pipeline-inputs.json").write_text(
        json.dumps(
            {
                "schema_version": "local-pipeline-inputs-v1",
                "gpx_path": str(gpx),
                "video_root": str(package),
                "output_language": "ja",
            }
        ),
        encoding="utf-8",
    )
    (package / "local-video-catalog.json").write_text(
        json.dumps(
            {
                "schema_version": "local-video-catalog-v1",
                "video_to_gps_offset_s": camera_offset_s,
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return package


def test_the_camera_clock_gives_the_local_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path, "d1", "2026-03-01T20:00:00Z")
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)

    assert local_offset_s(package) == 13 * 3600.0

    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "+09:00")
    assert local_offset_s(package) == 9 * 3600.0
    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "nine")
    with pytest.raises(ValueError):
        local_offset_s(package)


def test_a_camera_on_utc_gives_no_local_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path, "d1", "2026-03-01T20:00:00Z", camera_offset_s=-4.0)
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)

    assert local_offset_s(package) is None


def test_consecutive_days_beside_each_other_make_a_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    # Evening UTC is the next morning on the local clock (+13).
    first = _package(tmp_path, "a", "2026-03-01T20:00:00Z")
    second = _package(tmp_path, "b", "2026-03-02T19:30:00Z")
    third = _package(tmp_path, "c", "2026-03-03T21:00:00Z")
    _package(tmp_path, "unrelated", "2026-05-20T20:00:00Z")

    assert package_date(first, 13 * 3600.0).isoformat() == "2026-03-02"
    assert trip_day(first, local_offset=13 * 3600.0) == 1
    assert trip_day(second, local_offset=13 * 3600.0) == 2
    assert trip_day(third, local_offset=13 * 3600.0) == 3
    assert trip_day(tmp_path / "unrelated", local_offset=13 * 3600.0) is None
    assert day_label(2) == "Day 2" and day_label(None) is None


def test_a_package_without_a_track_date_has_no_day(tmp_path: Path) -> None:
    package = tmp_path / "empty"
    package.mkdir()

    assert trip_day(package) is None


def test_the_zone_thresholds_are_inclusive_at_the_near_edge_and_exclusive_past_the_far_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    # Exactly 30 minutes reads as a zone; a second under does not (it's drift).
    at_min = _package(tmp_path, "at-min", "2026-03-01T20:00:00Z", camera_offset_s=-1800.0)
    below_min = _package(tmp_path, "below-min", "2026-03-01T20:00:00Z", camera_offset_s=-1799.0)
    assert local_offset_s(at_min) == 1800.0
    assert local_offset_s(below_min) is None
    # Exactly 14 hours still reads as a zone; a second past does not (nonsense).
    at_max = _package(tmp_path, "at-max", "2026-03-01T20:00:00Z", camera_offset_s=-14 * 3600.0)
    above_max = _package(
        tmp_path, "above-max", "2026-03-01T20:00:00Z", camera_offset_s=-(14 * 3600.0 + 1.0)
    )
    assert local_offset_s(at_max) == 14 * 3600.0
    assert local_offset_s(above_max) is None


def test_the_env_override_parses_one_digit_hours_and_a_negative_sign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path, "d1", "2026-03-01T20:00:00Z")
    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "-9:00")
    assert local_offset_s(package) == -9 * 3600.0
    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "+5:30")
    assert local_offset_s(package) == 5 * 3600.0 + 30 * 60.0
    # The colon is optional; the digits still parse the same way.
    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "+1300")
    assert local_offset_s(package) == 13 * 3600.0
    # A sign is required -- without one the string doesn't match at all.
    monkeypatch.setenv("RIDE_LOCAL_UTC_OFFSET", "1300")
    with pytest.raises(ValueError):
        local_offset_s(package)


def test_a_missing_or_malformed_catalog_gives_no_local_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    no_catalog = tmp_path / "no-catalog"
    no_catalog.mkdir()
    assert local_offset_s(no_catalog) is None

    bad_json = tmp_path / "bad-json"
    bad_json.mkdir()
    (bad_json / "local-video-catalog.json").write_text("{not json", encoding="utf-8")
    assert local_offset_s(bad_json) is None

    missing_key = tmp_path / "missing-key"
    missing_key.mkdir()
    (missing_key / "local-video-catalog.json").write_text(
        json.dumps({"schema_version": "local-video-catalog-v1", "entries": []}), encoding="utf-8"
    )
    assert local_offset_s(missing_key) is None


def test_first_time_reads_the_head_of_the_gpx_and_refuses_what_it_cannot_parse(
    tmp_path: Path,
) -> None:
    assert _first_time(tmp_path / "does-not-exist.gpx") is None

    no_tag = tmp_path / "no-tag.gpx"
    no_tag.write_text(
        '<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="1" lon="2"/></trkseg></trk></gpx>',
        encoding="utf-8",
    )
    assert _first_time(no_tag) is None

    bad_text = tmp_path / "bad-text.gpx"
    bad_text.write_text(
        "<gpx><trk><trkseg><trkpt><time>not-a-date</time></trkpt></trkseg></trk></gpx>",
        encoding="utf-8",
    )
    assert _first_time(bad_text) is None

    # A timestamp without a zone is treated as UTC rather than rejected.
    naive = tmp_path / "naive.gpx"
    naive.write_text(
        "<gpx><trk><trkseg><trkpt><time>2026-03-01T20:00:00</time></trkpt></trkseg></trk></gpx>",
        encoding="utf-8",
    )
    stamp = _first_time(naive)
    assert stamp is not None
    assert stamp.tzinfo is not None and stamp.isoformat() == "2026-03-01T20:00:00+00:00"


def test_package_date_is_none_without_readable_pipeline_inputs(tmp_path: Path) -> None:
    no_inputs = tmp_path / "no-inputs"
    no_inputs.mkdir()
    assert package_date(no_inputs, 0.0) is None

    bad_json = tmp_path / "bad-inputs"
    bad_json.mkdir()
    (bad_json / "local-pipeline-inputs.json").write_text("not json", encoding="utf-8")
    assert package_date(bad_json, 0.0) is None

    missing_key = tmp_path / "missing-gpx-key"
    missing_key.mkdir()
    (missing_key / "local-pipeline-inputs.json").write_text(
        json.dumps({"schema_version": "local-pipeline-inputs-v1"}), encoding="utf-8"
    )
    assert package_date(missing_key, 0.0) is None


def test_a_gap_day_does_not_join_a_run_and_stays_a_day_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    first = _package(tmp_path, "a", "2026-03-01T20:00:00Z")
    # Four days later, not the next day -- no run to join.
    later = _package(tmp_path, "b", "2026-03-05T20:00:00Z")

    assert trip_day(first, local_offset=0.0) is None
    assert trip_day(later, local_offset=0.0) is None


def test_a_symlinked_sibling_is_not_counted_towards_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    mine = _package(tmp_path, "c", "2026-03-01T20:00:00Z")
    real_next = _package(elsewhere, "real-next", "2026-03-02T20:00:00Z")
    (tmp_path / "symlinked-next").symlink_to(real_next)

    # The only consecutive day is reachable solely through the symlink,
    # which `trip_day` skips -- so this still reads as a lone day trip.
    assert trip_day(mine, local_offset=0.0) is None


def test_a_plain_sibling_directory_without_a_package_is_skipped_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RIDE_LOCAL_UTC_OFFSET", raising=False)
    mine = _package(tmp_path, "e", "2026-03-01T20:00:00Z")
    (tmp_path / "not-a-package").mkdir()

    assert trip_day(mine, local_offset=0.0) is None
