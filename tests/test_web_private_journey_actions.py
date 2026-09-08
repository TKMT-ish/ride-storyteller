"""Synthetic-fixture tests for starting jobs from the console's server routes.

The runner is swapped for one that never runs, so a job "starts" and stays
running without touching FFmpeg or Google. What is held is the shape of the
door: POST only, a small JSON body, the figure to the yen, one job at a
time, and nothing at all in the public demo.
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
from app.web import server
from app.web.private_journey_actions import PrivateJourneyJobs
from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _post(path: str, body: object = None, *, method: str = "POST") -> tuple[str, dict]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    if isinstance(body, bytes):
        raw = body
    else:
        raw = b"" if body is None else json.dumps(body).encode("utf-8")
    out = b"".join(
        server.application(
            {
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "REQUEST_METHOD": method,
                "CONTENT_LENGTH": str(len(raw)),
                "wsgi.input": BytesIO(raw),
            },
            start_response,
        )
    )
    return str(captured["status"]), json.loads(out) if out else {}


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


@pytest.fixture
def held_jobs(monkeypatch: pytest.MonkeyPatch) -> list:
    """Jobs start and stay running; nothing is ever executed."""
    held: list = []
    monkeypatch.setattr(
        server,
        "_PRIVATE_JOURNEY_JOBS",
        PrivateJourneyJobs(runner=lambda target: held.append(target)),
    )
    return held


def _figure(package: Path) -> float:
    from app.web.private_journey_console import PrivateJourneyConsole

    stages = PrivateJourneyConsole.from_directory(package).payload()["stages"]
    return float(next(s for s in stages if s["key"] == "footage_planned")["cost_jpy"])


# --- the door -----------------------------------------------------------------------


def test_only_post_opens_a_job(package: Path, held_jobs: list) -> None:
    for path in ("preflight", "judge", "film"):
        status, _ = _post(f"/api/private-journey/{path}", method="GET")
        assert status == "405 Method Not Allowed"
    assert held_jobs == []


def test_preflight_starts_and_the_console_shows_it_running(package: Path, held_jobs: list) -> None:
    status, body = _post("/api/private-journey/preflight", {})

    assert status == "202 Accepted"
    assert body["job"]["kind"] == "preflight"
    assert body["job"]["state"] == "running"
    assert len(held_jobs) == 1

    from tests.test_web_private_journey_console import _request

    _, _, console = _request("/api/private-journey")
    assert json.loads(console)["job"]["state"] == "running"


def test_a_second_job_while_one_runs_is_a_conflict(package: Path, held_jobs: list) -> None:
    _post("/api/private-journey/preflight", {})

    status, body = _post("/api/private-journey/film", {"music": "rising-tide"})

    assert status == "409 Conflict"
    assert body["error"] == "another_job_is_running"
    assert len(held_jobs) == 1


def test_a_body_that_is_not_a_small_json_object_is_refused(package: Path, held_jobs: list) -> None:
    for raw in (b"not json", b"[1,2]", b"x" * 5000):
        status, body = _post("/api/private-journey/film", raw)
        assert status == "400 Bad Request", raw[:10]
        assert body["error"] == "invalid_request_body"
    assert held_jobs == []


# --- buying needs the figure shown, to the yen --------------------------------------


def test_judging_without_the_figure_is_refused_and_starts_nothing(
    package: Path, held_jobs: list
) -> None:
    for body in ({}, {"approve_jpy": "0", "bucket": "rides"}, {"approve_jpy": "99", "bucket": "b"}):
        status, out = _post("/api/private-journey/judge", body)
        assert status == "400 Bad Request"
        assert out["error"] == "approval_does_not_match_the_figure"
    assert held_jobs == []


def test_judging_with_the_figure_but_no_bucket_is_refused(package: Path, held_jobs: list) -> None:
    status, out = _post("/api/private-journey/judge", {"approve_jpy": _figure(package)})

    assert status == "400 Bad Request"
    assert out["error"] == "bucket_required"
    assert held_jobs == []


def test_judging_with_the_figure_and_a_bucket_starts(package: Path, held_jobs: list) -> None:
    status, out = _post(
        "/api/private-journey/judge", {"approve_jpy": str(_figure(package)), "bucket": "rides"}
    )

    assert status == "202 Accepted"
    assert out["job"]["kind"] == "judge"
    assert len(held_jobs) == 1


def test_an_unknown_track_never_starts_the_film(package: Path, held_jobs: list) -> None:
    status, out = _post("/api/private-journey/film", {"music": "../etc"})

    assert status == "400 Bad Request"
    assert out["error"] == "unknown_music_track"
    assert held_jobs == []


# --- nowhere in the public demo -------------------------------------------------------


def test_the_public_demo_starts_nothing(
    package: Path, held_jobs: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    for path in ("preflight", "judge", "film"):
        status, _ = _post(f"/api/private-journey/{path}", {"approve_jpy": "1", "bucket": "b"})
        assert status.startswith(("403", "404", "405", "413"))
    assert held_jobs == []


def test_an_unconfigured_machine_cannot_start_a_job(
    held_jobs: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.chdir(Path(__file__).parent)

    status, _ = _post("/api/private-journey/preflight", {})

    assert status == "503 Service Unavailable"
    assert held_jobs == []
