"""Synthetic-fixture tests for bringing a new day in through the server.

Held: the intake routes take paths only inside the intake root, build a
package only with a proposed offset, switch the console to the package
they built, let a person switch between packages by name -- and none of
it in the public demo. The clock proposal is stubbed; no video is probed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from app.clock_offset import ClockOffsetCandidate, ClockOffsetProposal
from app.web import server
from app.web.private_journey_actions import PrivateJourneyJobs, run_inline
from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV

_RIDE_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _post(path: str, body: object = None, *, method: str = "POST") -> tuple[str, dict]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

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


def _candidate(offset_s: float, inside: int) -> ClockOffsetCandidate:
    return ClockOffsetCandidate(
        offset_s=offset_s,
        recordings_inside=inside,
        recordings_clipped=0,
        recordings_total=3,
        covered_ride_s=600.0,
        ride_duration_s=3600.0,
        lead_in_s=0.0,
        lead_out_s=0.0,
    )


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    intake = tmp_path / "input"
    work = tmp_path / "work"
    intake.mkdir()
    work.mkdir()
    monkeypatch.setenv("RIDE_PRIVATE_INTAKE_ROOT", str(intake))
    monkeypatch.setenv("RIDE_PRIVATE_WORK_ROOT", str(work))
    monkeypatch.delenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.setattr(server, "_CURRENT_PACKAGE", None)
    monkeypatch.setattr(server, "_PRIVATE_JOURNEY_JOBS", PrivateJourneyJobs(runner=run_inline))
    return intake, work


@pytest.fixture
def day(roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    intake, _ = roots
    folder = intake / "day-two"
    folder.mkdir()
    gpx = _gpx(folder / "ride.gpx")
    videos = folder / "videos"
    videos.mkdir()
    (videos / "GH010001.MP4").write_bytes(b"a recording")
    monkeypatch.setattr(
        "app.web.private_journey_intake.propose_clock_offset",
        lambda g, v: ClockOffsetProposal(best=_candidate(-46_800.0, 2), runners_up=()),
    )
    return gpx, videos


def _fake_prepare(gpx, videos, destination, **kwargs):
    """Stand in for the pipeline: write the two files the console needs."""
    from app.agents import StoryOutputLanguage
    from app.local_pipeline import LocalPipelineInputs
    from app.video import VideoCatalog, VideoCatalogEntry

    destination.mkdir(parents=True)
    inputs = LocalPipelineInputs(
        gpx_path=gpx.resolve(),
        video_root=videos.resolve(),
        video_to_gps_offset_s=kwargs["video_to_gps_offset_s"],
        target_duration_s=kwargs["target_duration_s"],
        output_language=StoryOutputLanguage.JAPANESE,
    )
    (destination / "local-pipeline-inputs.json").write_text(
        json.dumps(inputs.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    catalog = VideoCatalog(
        entries=(
            VideoCatalogEntry(
                asset_id="asset-1",
                file_name="GH010001.MP4",
                recorded_start_time=_RIDE_START + timedelta(seconds=600 + 46_800),
                duration_s=120.0,
            ),
        ),
        video_to_gps_offset_s=kwargs["video_to_gps_offset_s"],
    )
    (destination / "local-video-catalog.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False), encoding="utf-8"
    )


# --- proposing --------------------------------------------------------------------------


def test_proposing_returns_the_evidence_and_nothing_else(day) -> None:
    status, body = _post(
        "/api/private-journey/intake/propose",
        {"gpx": "day-two/ride.gpx", "video_root": "day-two/videos"},
    )

    assert status == "200 OK"
    assert body["proposed"]["offset_s"] == -46_800.0
    assert body["is_unambiguous"] is True
    assert "day-two" not in json.dumps(body)


def test_a_path_outside_the_intake_root_is_refused_with_a_reason(day, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.gpx"
    outside.write_text("x", encoding="utf-8")

    status, body = _post(
        "/api/private-journey/intake/propose",
        {"gpx": str(outside), "video_root": "day-two/videos"},
    )

    assert status == "400 Bad Request"
    assert body["error"] in {"path_outside_the_intake_root", "path_is_a_symlink_or_missing"}


def test_intake_is_post_only(day) -> None:
    for path in ("intake/propose", "intake/create", "select"):
        status, _ = _post(f"/api/private-journey/{path}", method="GET")
        assert status == "405 Method Not Allowed"


# --- creating, and the console following ----------------------------------------------


def test_creating_with_the_proposed_offset_builds_and_switches(
    day, roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.web.private_journey_intake.prepare_local_review_package", _fake_prepare
    )

    status, body = _post(
        "/api/private-journey/intake/create",
        {
            "gpx": "day-two/ride.gpx",
            "video_root": "day-two/videos",
            "name": "day-two",
            "offset_s": "-46800",
            "target_duration_s": "300",
        },
    )

    assert status == "202 Accepted"
    assert body["job"]["kind"] == "intake"
    assert body["job"]["state"] == "done"
    assert body["job"]["result"] == {"package": "day-two"}
    assert (roots[1] / "day-two" / "local-video-catalog.json").is_file()

    from tests.test_web_private_journey_console import _request

    _, _, console = _request("/api/private-journey")
    payload = json.loads(console)
    assert payload["package"] == "day-two"
    assert "day-two" in payload["packages"]
    assert payload["stages"][0]["key"] == "footage_planned"


def test_creating_with_a_number_that_was_not_proposed_builds_nothing(
    day, roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list = []
    monkeypatch.setattr(
        "app.web.private_journey_intake.prepare_local_review_package",
        lambda *a, **k: built.append(1),
    )

    status, body = _post(
        "/api/private-journey/intake/create",
        {"gpx": "day-two/ride.gpx", "video_root": "day-two/videos", "name": "x", "offset_s": "0"},
    )

    # The cheap checks pass; the offset is confirmed inside the job and fails there.
    assert status == "202 Accepted"
    assert body["job"]["state"] == "failed"
    assert body["job"]["reason"] == "offset_was_not_the_one_proposed"
    assert built == []
    assert not (roots[1] / "x").exists()


def test_a_bad_name_or_existing_package_is_refused_before_a_job(day, roots) -> None:
    (roots[1] / "taken").mkdir()
    for name, reason in (
        ("../x", "package_name_is_not_a_plain_word"),
        ("taken", "package_already_exists"),
    ):
        status, body = _post(
            "/api/private-journey/intake/create",
            {
                "gpx": "day-two/ride.gpx",
                "video_root": "day-two/videos",
                "name": name,
                "offset_s": "-46800",
            },
        )
        assert status == "400 Bad Request"
        assert body["error"] == reason


# --- switching between packages by name -----------------------------------------------


def test_selecting_an_existing_package_switches_the_console(
    day, roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.web.private_journey_intake.prepare_local_review_package", _fake_prepare
    )
    for name in ("first", "second"):
        _post(
            "/api/private-journey/intake/create",
            {
                "gpx": "day-two/ride.gpx",
                "video_root": "day-two/videos",
                "name": name,
                "offset_s": "-46800",
            },
        )

    status, body = _post("/api/private-journey/select", {"name": "first"})

    assert status == "200 OK"
    assert body["package"] == "first"
    assert server._CURRENT_PACKAGE == (roots[1] / "first").resolve()


def test_selecting_a_package_that_is_not_there_is_refused(day) -> None:
    status, body = _post("/api/private-journey/select", {"name": "nowhere"})

    assert status == "400 Bad Request"
    assert body["error"] == "package_does_not_exist"


# --- nowhere in the public demo -------------------------------------------------------


def test_the_public_demo_takes_nothing_in(day, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    for path in ("intake/propose", "intake/create", "select"):
        status, _ = _post(f"/api/private-journey/{path}", {"name": "x"})
        assert status.startswith(("403", "404", "405", "413"))
