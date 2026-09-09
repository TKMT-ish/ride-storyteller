"""Synthetic-fixture tests for the product-facing workflow page on the server.

The page is served locally, by GET, in both languages, with or without a
configured package (the page itself shows the intake form when the API says
503); it offers exactly the music the film step accepts; and the public demo
refuses it and every private route it calls.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from app.web.journey_workflow_frontend import WORKFLOW_FRONTEND_SCHEMA_VERSION
from app.web.private_journey_actions import MUSIC_TRACK_IDS, NO_MUSIC_TRACK_ID
from app.web.private_journey_status import PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV
from app.web.server import application

_PRIVATE_ROUTES = (
    "/api/private-journey",
    "/api/private-journey/story",
    "/api/private-journey/preflight",
    "/api/private-journey/judge",
    "/api/private-journey/film",
    "/api/private-journey/intake/propose",
    "/api/private-journey/intake/create",
    "/api/private-journey/select",
    "/private-journey/film",
)


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


@pytest.fixture
def local_without_a_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.delenv(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.chdir(Path(__file__).parent)  # no .env here


def test_the_page_is_served_in_both_languages_before_any_package_exists(
    local_without_a_package: None,
) -> None:
    """A new machine's first screen is the intake form, so the page must not need a package."""
    ja_status, ja_headers, ja_body = _request("/workflow")
    en_status, _, en_body = _request("/workflow", query="lang=en")

    assert ja_status == en_status == "200 OK"
    assert ja_headers["Content-Type"] == "text/html; charset=utf-8"
    assert "一日の旅を、一本の物語へ。" in ja_body.decode()
    assert "新しい旅を取り込む" in ja_body.decode()
    assert "Turn one riding day into a story" in en_body.decode()
    assert 'href="/workflow?lang=ja"' in en_body.decode()
    assert WORKFLOW_FRONTEND_SCHEMA_VERSION in ja_body.decode()
    api_status, _, api_body = _request("/api/private-journey")
    assert api_status == "503 Service Unavailable"
    assert b"unavailable" in api_body


def test_the_page_calls_only_the_existing_private_journey_routes(
    local_without_a_package: None,
) -> None:
    _, _, body = _request("/workflow")
    page = body.decode()

    assert 'API="/api/private-journey"' in page
    assert 'API+"/story"' in page
    assert 'API+"/intake/"+a' in page
    assert 'src="/private-journey/film"' in page
    assert "https://" not in page
    assert "http://" not in page


def test_the_page_offers_exactly_the_music_the_film_step_accepts(
    local_without_a_package: None,
) -> None:
    """A track the server would refuse must not be offered; one it accepts must be."""
    _, _, body = _request("/workflow")
    page = body.decode()

    assert "wandering" in MUSIC_TRACK_IDS
    for track_id in (NO_MUSIC_TRACK_ID, *MUSIC_TRACK_IDS):
        assert f'"{track_id}"' in page
    assert '"Wandering"' in page
    assert '"Enchanted Valley"' in page


def test_only_get_is_accepted(local_without_a_package: None) -> None:
    status, _, _ = _request("/workflow", method="POST")

    assert status == "405 Method Not Allowed"


def test_the_page_carries_no_private_identity_field_or_path(
    local_without_a_package: None,
) -> None:
    _, _, body = _request("/workflow")
    page = body.decode()

    for name in (
        "source_asset_id",
        "source_start_sec",
        "source_end_sec",
        "latitude",
        "longitude",
        "capture_time",
        "/Users/",
        "private-media",
    ):
        assert name not in page


def test_the_response_carries_the_servers_protective_headers(
    local_without_a_package: None,
) -> None:
    _, headers, _ = _request("/workflow")

    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_the_public_demo_refuses_the_page_and_every_route_it_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    status, _, body = _request("/workflow")
    assert status == "403 Forbidden"
    assert b"disabled in public demo mode" in body
    for path in _PRIVATE_ROUTES:
        status, _, _ = _request(path)
        assert status == "403 Forbidden", path
        status, _, _ = _request(path, method="POST")
        assert status.startswith(("403", "405")), path
