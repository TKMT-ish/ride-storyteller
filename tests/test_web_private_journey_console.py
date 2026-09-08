"""Synthetic-fixture tests for the console's page and API on the server.

The console reads; the server must let it be read only by GET, only when a
package is configured, and never in the public demo.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.local_pipeline import LocalPipelineInputs
from app.video import VideoCatalog, VideoCatalogEntry
from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV
from app.web.server import application

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _request(path: str, *, method: str = "GET", query: str = "") -> tuple[str, dict, bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        application(
            {
                "PATH_INFO": path,
                "QUERY_STRING": query,
                "REQUEST_METHOD": method,
                "CONTENT_LENGTH": "0",
                "wsgi.input": BytesIO(b""),
            },
            start_response,
        )
    )
    return str(captured["status"]), captured["headers"], body  # type: ignore[return-value]


def _gpx(path: Path, *, span_s: float = 4 * 3600.0, point_count: int = 60) -> Path:
    step = span_s / (point_count - 1)
    points = "".join(
        '<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>100</ele><time>{t}</time></trkpt>'.format(
            lat=35.0 + 0.001 * index,
            lon=139.0 + 0.001 * index,
            t=(_RIDE_START + timedelta(seconds=step * index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for index in range(point_count)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + points
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "package"
    root.mkdir()
    (root / "synthetic.mp4").write_bytes(b"a recording")
    inputs = LocalPipelineInputs(
        gpx_path=_gpx(root / "ride.gpx").resolve(),
        video_root=root.resolve(),
        video_to_gps_offset_s=0.0,
        target_duration_s=300.0,
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (root / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-synthetic-1",
                file_name="synthetic.mp4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600),
                duration_s=120.0,
            ),
        ),
        video_to_gps_offset_s=0.0,
    )
    (root / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, str(root))
    return root


def test_the_api_reads_the_configured_package(package: Path) -> None:
    status, headers, body = _request("/api/private-journey")

    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    payload = json.loads(body)
    assert payload["stages"][0]["key"] == "footage_planned"
    assert payload["stages"][0]["cost_jpy"] > 0
    assert payload["external_data_sent"] is False


def test_the_page_is_served_in_both_languages(package: Path) -> None:
    ja_status, ja_headers, ja_body = _request("/private-journey")
    en_status, _, en_body = _request("/private-journey", query="lang=en")

    assert ja_status == en_status == "200 OK"
    assert ja_headers["Content-Type"] == "text/html; charset=utf-8"
    assert "この旅の判定と作品" in ja_body.decode()
    assert "This ride, judged" in en_body.decode()
    assert '/api/private-journey"' in ja_body.decode()


def test_the_page_carries_no_path_from_the_package(package: Path) -> None:
    _, _, body = _request("/private-journey")
    _, _, api = _request("/api/private-journey")

    for haystack in (body.decode(), api.decode()):
        assert str(package) not in haystack
        assert "synthetic.mp4" not in haystack


def test_only_get_is_accepted(package: Path) -> None:
    for path in ("/private-journey", "/api/private-journey"):
        status, _, _ = _request(path, method="POST")
        assert status == "405 Method Not Allowed"


def test_an_unconfigured_machine_says_so_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.chdir(Path(__file__).parent)  # no .env here

    for path in ("/private-journey", "/api/private-journey"):
        status, _, body = _request(path)
        assert status == "503 Service Unavailable"
        assert b"unavailable" in body


def test_the_public_demo_never_serves_the_console(
    package: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    for path in ("/private-journey", "/api/private-journey"):
        status, _, _ = _request(path)
        assert status.startswith(("403", "404"))
