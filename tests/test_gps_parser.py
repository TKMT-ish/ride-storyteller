from datetime import UTC
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.gps import parse_gpx, parse_gpx_bytes
from app.gps.parser import _child_text, _distance_m, _parse_timestamp

FIXTURE = Path("tests/fixtures/sample_route.xml")

GPX_NS = 'xmlns="http://www.topografix.com/GPX/1/1"'


def _gpx(points: str, *, namespaced: bool = True) -> bytes:
    attrs = f" {GPX_NS}" if namespaced else ""
    return f"<gpx{attrs}><trk><trkseg>{points}</trkseg></trk></gpx>".encode()


def test_parse_gpx_normalizes_points_and_summary() -> None:
    route = parse_gpx(FIXTURE)
    assert route.summary.point_count == 3
    assert route.summary.total_distance_m > 0
    assert route.summary.duration_s == 60
    assert route.summary.elevation_gain_m == 5
    assert route.summary.elevation_loss_m == 3
    assert route.points[0].speed_mps is None
    assert route.points[1].speed_mps is not None
    assert route.to_dict()["points"][0]["timestamp"].endswith("Z")


def test_parse_gpx_rejects_missing_track_points(tmp_path: Path) -> None:
    empty = tmp_path / "empty.gpx"
    empty.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1" />')
    with pytest.raises(ValueError, match="no track points"):
        parse_gpx(empty)


def test_parse_gpx_bytes_keeps_private_upload_in_memory() -> None:
    route = parse_gpx_bytes(FIXTURE.read_bytes())

    assert route.summary.point_count == 3


def test_parse_gpx_rejects_track_point_without_time() -> None:
    xml = _gpx('<trkpt lat="1" lon="2"><ele>1</ele></trkpt>')
    with pytest.raises(ValueError, match="every GPX track point must include time"):
        parse_gpx_bytes(xml)


def test_parse_gpx_rejects_equal_consecutive_timestamps() -> None:
    xml = _gpx(
        '<trkpt lat="1" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="1.001" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>'
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_gpx_bytes(xml)


def test_parse_gpx_rejects_decreasing_timestamps() -> None:
    xml = _gpx(
        '<trkpt lat="1" lon="2"><time>2026-01-01T00:00:10Z</time></trkpt>'
        '<trkpt lat="1.001" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>'
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_gpx_bytes(xml)


def test_parse_gpx_rejects_out_of_range_latitude() -> None:
    xml = _gpx('<trkpt lat="95" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>')
    with pytest.raises(ValueError, match="latitude must be between -90 and 90"):
        parse_gpx_bytes(xml)


def test_parse_gpx_rejects_out_of_range_longitude() -> None:
    xml = _gpx('<trkpt lat="1" lon="181"><time>2026-01-01T00:00:00Z</time></trkpt>')
    with pytest.raises(ValueError, match="longitude must be between -180 and 180"):
        parse_gpx_bytes(xml)


def test_parse_gpx_only_accumulates_elevation_when_both_points_have_it() -> None:
    # The middle point has no <ele>, so neither leg touching it should move
    # gain/loss -- only the (missing) first->second and second->third legs
    # are skipped, leaving the summary at zero even though endpoints differ.
    xml = _gpx(
        '<trkpt lat="1" lon="2"><ele>10</ele><time>2026-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="1.001" lon="2"><time>2026-01-01T00:00:10Z</time></trkpt>'
        '<trkpt lat="1.002" lon="2"><ele>20</ele><time>2026-01-01T00:00:20Z</time></trkpt>'
    )
    route = parse_gpx_bytes(xml)
    assert route.summary.elevation_gain_m == 0.0
    assert route.summary.elevation_loss_m == 0.0


def test_parse_gpx_accepts_gpx_without_a_namespace() -> None:
    xml = _gpx(
        '<trkpt lat="1" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="1.001" lon="2"><time>2026-01-01T00:00:10Z</time></trkpt>',
        namespaced=False,
    )
    route = parse_gpx_bytes(xml)
    assert route.summary.point_count == 2


def test_parse_gpx_normalizes_non_utc_offsets_to_utc() -> None:
    xml = _gpx('<trkpt lat="1" lon="2"><time>2026-01-01T11:42:15+09:00</time></trkpt>')
    route = parse_gpx_bytes(xml)
    assert route.points[0].timestamp.isoformat() == "2026-01-01T02:42:15+00:00"


def test_parse_gpx_first_point_has_zero_distance_and_no_speed() -> None:
    xml = _gpx('<trkpt lat="1" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>')
    route = parse_gpx_bytes(xml)
    assert route.points[0].distance_from_start_m == 0.0
    assert route.points[0].speed_mps is None


def test_parse_gpx_zero_movement_yields_zero_speed() -> None:
    xml = _gpx(
        '<trkpt lat="1" lon="2"><time>2026-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="1" lon="2"><time>2026-01-01T00:00:10Z</time></trkpt>'
    )
    route = parse_gpx_bytes(xml)
    assert route.points[1].speed_mps == 0.0
    assert route.points[1].distance_from_start_m == 0.0


def test_parse_timestamp_rejects_naive_value() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        _parse_timestamp("2026-01-01T00:00:00")


def test_parse_timestamp_accepts_z_suffix() -> None:
    timestamp = _parse_timestamp("2026-01-01T00:00:00Z")
    assert timestamp.tzinfo == UTC


def test_child_text_returns_none_when_missing() -> None:
    point = ElementTree.fromstring(
        '<trkpt xmlns="http://www.topografix.com/GPX/1/1" lat="1" lon="2" />'
    )
    assert _child_text(point, "ele") is None


def test_child_text_returns_value_when_present() -> None:
    point = ElementTree.fromstring(
        '<trkpt xmlns="http://www.topografix.com/GPX/1/1" lat="1" lon="2"><ele>42</ele></trkpt>'
    )
    assert _child_text(point, "ele") == "42"


def test_distance_m_is_zero_for_the_same_point() -> None:
    class Point:
        latitude = 0.0
        longitude = 0.0

    assert _distance_m(Point(), 0.0, 0.0) == 0.0


def test_distance_m_matches_known_equatorial_degree() -> None:
    class Point:
        latitude = 0.0
        longitude = 0.0

    # One degree of longitude at the equator is ~111.19 km.
    distance = _distance_m(Point(), 0.0, 1.0)
    assert distance == pytest.approx(111_194.9, abs=1.0)
