"""Synthetic-fixture tests for the story view and the film stream on the server.

Held: the story is served only by GET from the private console, says so
when there is no plan, and the film streams by byte range without ever
being read whole -- and none of it in the public demo.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from app.web import server
from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV
from app.web.private_journey_story import SCORED_FILM_FILE_NAME
from tests.test_private_journey_story import _package


def _get(path: str, *, headers: dict[str, str] | None = None, method: str = "GET"):
    captured: dict[str, object] = {}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ: dict[str, object] = {
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": "0",
        "wsgi.input": BytesIO(b""),
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    body = b"".join(server.application(environ, start_response))
    return str(captured["status"]), captured["headers"], body


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _package(tmp_path / "package")
    monkeypatch.setenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, str(root))
    monkeypatch.setattr(server, "_CURRENT_PACKAGE", None)
    return root


def test_the_story_is_served_from_the_private_console(package: Path) -> None:
    status, headers, body = _get("/api/private-journey/story")

    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    payload = json.loads(body)
    assert [c["title"] for c in payload["chapters"]] == ["出発", "町を抜ける", "今日はここまで"]
    assert payload["cold_open"]["rank"] == 1


def test_no_plan_is_a_404_not_a_traceback(package: Path) -> None:
    (package / "journey-story-plan.json").unlink()

    status, _, body = _get("/api/private-journey/story")

    assert status == "404 Not Found"
    assert b"no story plan" in body


def test_story_and_film_are_get_only(package: Path) -> None:
    for path in ("/api/private-journey/story", "/private-journey/film"):
        status, _, _ = _get(path, method="POST")
        assert status == "405 Method Not Allowed"


def test_the_film_streams_whole_and_by_range(package: Path) -> None:
    size = (package / SCORED_FILM_FILE_NAME).stat().st_size

    status, headers, body = _get("/private-journey/film")
    assert status == "200 OK"
    assert headers["Content-Type"] == "video/mp4"
    assert headers["Accept-Ranges"] == "bytes"
    assert len(body) == size

    status, headers, body = _get("/private-journey/film", headers={"Range": "bytes=100-199"})
    assert status == "206 Partial Content"
    assert headers["Content-Range"] == f"bytes 100-199/{size}"
    assert headers["Content-Length"] == "100"
    assert len(body) == 100

    status, headers, body = _get("/private-journey/film", headers={"Range": "bytes=-50"})
    assert status == "206 Partial Content"
    assert headers["Content-Range"] == f"bytes {size - 50}-{size - 1}/{size}"

    status, headers, _ = _get("/private-journey/film", headers={"Range": f"bytes={size + 5}-"})
    assert status == "416 Range Not Satisfiable"


def test_no_film_is_a_404(package: Path) -> None:
    (package / SCORED_FILM_FILE_NAME).unlink()

    status, _, body = _get("/private-journey/film")

    assert status == "404 Not Found"
    assert b"no film" in body


def test_the_public_demo_serves_neither(package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    for path in ("/api/private-journey/story", "/private-journey/film"):
        status, _, _ = _get(path)
        assert status.startswith(("403", "404"))
