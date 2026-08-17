from pathlib import Path

import pytest

from app.gps import parse_gpx, parse_gpx_bytes

FIXTURE = Path("tests/fixtures/sample_route.xml")


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
