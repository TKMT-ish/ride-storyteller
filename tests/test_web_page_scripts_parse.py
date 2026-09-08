"""The inline scripts the server serves must at least parse.

A page whose script fails to parse shows "Loading…" forever and logs
nothing a test would see. This happened once: a quote escaped for Python
inside an f-string arrived in the browser unescaped, and every function on
the console page was undefined. The Python tests all passed, because none
of them run JavaScript. This one does the one thing they could not: it
hands each page's script to Node's parser. Where Node is not installed the
test is skipped rather than pretending.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest

from app.web import server
from app.web.i18n import UiLanguage

_NODE = shutil.which("node")

PAGES = (
    "_private_journey_console_page",
    "_private_journey_status_page",
    "_private_highlight_review_page",
    "_private_highlight_reinforcement_review_page",
    "_private_evidence_review_page",
    "_private_director_preview_page",
    "_media_inventory_page",
)


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, flags=re.S)


@pytest.mark.skipif(_NODE is None, reason="node is not installed; cannot parse JavaScript")
@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("language", list(UiLanguage))
def test_the_pages_inline_script_parses(page: str, language: UiLanguage, tmp_path: Path) -> None:
    html = getattr(server, page)(language)
    scripts = _scripts(html)
    assert scripts, "the page has no inline script to check"
    for index, script in enumerate(scripts):
        path = tmp_path / f"{page}-{language.value}-{index}.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [_NODE, "--check", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr[-800:]


def test_the_home_page_still_answers() -> None:
    """A smoke check that the server's root is served, so the suite notices a broken import."""
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    body = b"".join(
        server.application(
            {
                "PATH_INFO": "/",
                "QUERY_STRING": "",
                "REQUEST_METHOD": "GET",
                "CONTENT_LENGTH": "0",
                "wsgi.input": BytesIO(b""),
            },
            start_response,
        )
    )
    assert str(captured["status"]).startswith("200")
    assert body
