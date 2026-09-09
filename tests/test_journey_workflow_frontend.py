"""Contract tests for the isolated product-facing workflow frontend."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

import pytest

from app.web import journey_workflow_preview as journey_workflow_preview_module
from app.web.i18n import UiLanguage
from app.web.journey_workflow_frontend import (
    WORKFLOW_FRONTEND_SCHEMA_VERSION,
    render_journey_workflow_page,
)
from app.web.journey_workflow_preview import application

_NODE = shutil.which("node")


def _request(
    path: str, *, method: str = "GET", query: str = ""
) -> tuple[str, dict[str, str], bytes]:
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


def test_japanese_page_is_a_complete_journey_workflow() -> None:
    page = render_journey_workflow_page()

    assert 'lang="ja"' in page
    assert "一日の旅を、一本の物語へ。" in page
    assert "新しい旅を取り込む" in page
    assert "完成までの進捗" in page
    assert "次にすること" in page
    assert "この旅の物語" in page
    assert WORKFLOW_FRONTEND_SCHEMA_VERSION in page


def test_english_page_has_the_language_switch_and_product_copy() -> None:
    page = render_journey_workflow_page(UiLanguage.ENGLISH)

    assert 'lang="en"' in page
    assert "Turn one riding day into a story" in page
    assert 'href="/workflow?lang=ja"' in page
    assert "Add another riding day" in page


def test_page_uses_only_existing_private_journey_endpoints() -> None:
    page = render_journey_workflow_page()

    assert 'API="/api/private-journey"' in page
    assert "/private-journey/film" in page
    assert 'API+"/story"' in page
    assert 'API+"/intake/"+a' in page
    assert "https://" not in page
    assert "http://" not in page


def test_page_does_not_embed_private_identity_fields() -> None:
    page = render_journey_workflow_page()

    forbidden = (
        "source_asset_id",
        "source_start_sec",
        "source_end_sec",
        "latitude",
        "longitude",
        "capture_time",
    )
    assert all(name not in page for name in forbidden)


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
@pytest.mark.parametrize("language", list(UiLanguage))
def test_inline_script_parses(
    language: UiLanguage, tmp_path: Path
) -> None:
    page = render_journey_workflow_page(language)
    scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.S)
    assert len(scripts) == 1
    script = tmp_path / f"workflow-{language.value}.js"
    script.write_text(scripts[0], encoding="utf-8")

    result = subprocess.run(
        [_NODE, "--check", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-800:]


def test_preview_serves_the_workflow_in_both_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    status, headers, japanese = _request("/workflow")
    english_status, _, english = _request("/workflow", query="lang=en")

    assert status == english_status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "一日の旅を、一本の物語へ。".encode() in japanese
    assert b"Turn one riding day into a story" in english


def test_preview_is_get_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "local")

    status, _, _ = _request("/workflow", method="POST")

    assert status == "405 Method Not Allowed"


def test_preview_fails_closed_in_public_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    status, _, body = _request("/workflow")

    assert status == "403 Forbidden"
    assert body == b"local workflow only"


def test_preview_delegates_paths_outside_the_workflow_to_the_existing_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    delegated_paths: list[str] = []

    def fake_existing_application(
        environ: dict[str, object], start_response: object
    ) -> Iterable[bytes]:
        delegated_paths.append(str(environ["PATH_INFO"]))
        start_response("200 OK", [("Content-Type", "text/plain")])  # type: ignore[operator]
        return [b"delegated"]

    monkeypatch.setattr(
        journey_workflow_preview_module, "existing_application", fake_existing_application
    )

    status, _, body = _request("/api/private-journey/status")

    assert status == "200 OK"
    assert body == b"delegated"
    assert delegated_paths == ["/api/private-journey/status"]


def test_main_rejects_a_port_outside_the_valid_range(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["journey_workflow_preview", "--port", "70000"])

    with pytest.raises(SystemExit):
        journey_workflow_preview_module.main()

    assert "--port must be between 1 and 65535" in capsys.readouterr().err


def test_main_starts_the_server_on_the_requested_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: dict[str, object] = {}

    class FakeServer:
        def __enter__(self) -> "FakeServer":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def serve_forever(self) -> None:
            started["served"] = True

    def fake_make_server(host: str, port: int, app: object) -> FakeServer:
        started["host"] = host
        started["port"] = port
        started["app"] = app
        return FakeServer()

    monkeypatch.setattr(journey_workflow_preview_module, "make_server", fake_make_server)
    monkeypatch.setattr(sys, "argv", ["journey_workflow_preview", "--port", "9001"])

    journey_workflow_preview_module.main()

    assert started == {
        "host": "127.0.0.1",
        "port": 9001,
        "app": journey_workflow_preview_module.application,
        "served": True,
    }
    assert "http://127.0.0.1:9001/workflow" in capsys.readouterr().out
