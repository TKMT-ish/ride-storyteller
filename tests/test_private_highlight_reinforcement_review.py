"""Tests for the loopback-only private highlight reinforcement conflict review."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from app.video.highlight_quality import QualitySelectionMethod
from app.video.highlight_story_bridge import (
    HighlightReinforcementConflict,
    HighlightReinforcementConflictSet,
    HighlightReinforcementSelection,
    HighlightReinforcementSelectionSet,
    load_highlight_reinforcement_selections,
    write_highlight_reinforcement_conflicts,
    write_highlight_reinforcement_selections,
)
from app.web.i18n import UiLanguage
from app.web.private_highlight_reinforcement_review import (
    PrivateHighlightReinforcementReviewError,
    PrivateHighlightReinforcementReviewSession,
)
from app.web.server import (
    _private_highlight_reinforcement_review_page,
    application,
)

_EVENT_A = "evt_001"
_EVENT_B = "evt_002"


def _create_package(root: Path) -> HighlightReinforcementConflictSet:
    conflicts = HighlightReinforcementConflictSet(
        (
            HighlightReinforcementConflict(
                _EVENT_A, "highlight-a1", QualitySelectionMethod.QUALITY_FIRST, 1
            ),
            HighlightReinforcementConflict(
                _EVENT_A, "highlight-a2", QualitySelectionMethod.RIDE_DYNAMICS, 1
            ),
            HighlightReinforcementConflict(
                _EVENT_B, "highlight-b1", QualitySelectionMethod.SCENIC_CONTEXT, 1
            ),
            HighlightReinforcementConflict(
                _EVENT_B, "highlight-b2", QualitySelectionMethod.BALANCED_DIVERSE, 1
            ),
        )
    )
    write_highlight_reinforcement_conflicts(
        root / "highlight-reinforcement-conflicts.json", conflicts
    )
    for conflict in conflicts.conflicts:
        method_dir = root / conflict.method.value
        method_dir.mkdir(parents=True, exist_ok=True)
        (method_dir / f"clip-{conflict.rank:02d}.mp4").write_bytes(b"private-video")
    thumbnail_root = root / "review-thumbnails"
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    for conflict in conflicts.conflicts:
        (thumbnail_root / f"{conflict.method.value}-clip-{conflict.rank:02d}.jpg").write_bytes(
            b"private-thumbnail"
        )
    return conflicts


def _request(
    path: str,
    *,
    body: bytes = b"",
    method: str = "GET",
    query_string: str = "",
    extra_environ: dict[str, str] | None = None,
) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ: dict[str, object] = {
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "REQUEST_METHOD": method,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
    }
    if extra_environ:
        environ.update(extra_environ)
    response = b"".join(application(environ, start_response))
    return captured["status"], captured["headers"], response  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Payload redaction
# ---------------------------------------------------------------------------


def test_payload_exposes_only_opaque_tokens_never_raw_identifiers(tmp_path: Path) -> None:
    _create_package(tmp_path)

    payload = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path).payload()
    serialized = json.dumps(payload)

    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False
    assert payload["review"]["conflict_count"] == 2
    assert payload["review"]["conflict_option_count"] == 4
    for forbidden in (
        _EVENT_A,
        _EVENT_B,
        "highlight-a1",
        "highlight-a2",
        "highlight-b1",
        "highlight-b2",
        str(tmp_path),
        "private-video",
        "private-thumbnail",
    ):
        assert forbidden not in serialized
    tokens = {
        option["review_token"]
        for conflict in payload["review"]["conflicts"]
        for option in conflict["options"]
    }
    assert tokens == {
        "reinforcement-001",
        "reinforcement-002",
        "reinforcement-003",
        "reinforcement-004",
    }
    first_option = payload["review"]["conflicts"][0]["options"][0]
    assert set(first_option) == {"review_token", "method", "rank", "thumbnail_url", "media_url"}


def test_payload_groups_options_by_their_own_conflict_only(tmp_path: Path) -> None:
    _create_package(tmp_path)

    payload = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path).payload()

    groups = payload["review"]["conflicts"]
    assert [len(group["options"]) for group in groups] == [2, 2]


# ---------------------------------------------------------------------------
# Tokens cannot be replayed as raw identifiers
# ---------------------------------------------------------------------------


def test_token_cannot_be_replayed_as_a_raw_candidate_or_event_id(tmp_path: Path) -> None:
    _create_package(tmp_path)
    session = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)

    for raw_identifier in ("highlight-a1", _EVENT_A, "reinforcement-001x", "", "../etc/passwd"):
        with pytest.raises(PrivateHighlightReinforcementReviewError, match="unknown"):
            session.update(review_token=raw_identifier)
        with pytest.raises(PrivateHighlightReinforcementReviewError, match="unknown"):
            session.asset(raw_identifier, "media")


def test_asset_lookup_never_reaches_outside_the_configured_root(tmp_path: Path) -> None:
    """A crafted token cannot be used for path traversal: tokens only ever
    resolve to a fixed enum method value and an integer rank, never to
    browser-supplied path text."""
    _create_package(tmp_path)
    session = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)

    with pytest.raises(PrivateHighlightReinforcementReviewError, match="unknown"):
        session.asset("reinforcement-001/../../../../etc/passwd", "media")
    with pytest.raises(PrivateHighlightReinforcementReviewError, match="unknown"):
        session.asset("reinforcement-001", "../../etc/passwd")


# ---------------------------------------------------------------------------
# Saving a selection
# ---------------------------------------------------------------------------


def test_valid_token_saves_the_corresponding_event_candidate_pair(tmp_path: Path) -> None:
    _create_package(tmp_path)
    session = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)

    session.update(review_token="reinforcement-001")

    saved = load_highlight_reinforcement_selections(
        tmp_path / "highlight-reinforcement-selections.json"
    )
    assert saved == HighlightReinforcementSelectionSet(
        (HighlightReinforcementSelection(_EVENT_A, "highlight-a1"),)
    )


def test_second_choice_for_same_event_replaces_only_that_selection(tmp_path: Path) -> None:
    _create_package(tmp_path)
    session = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)

    session.update(review_token="reinforcement-001")  # evt_001 -> highlight-a1
    session.update(review_token="reinforcement-003")  # evt_002 -> highlight-b1
    session.update(review_token="reinforcement-004")  # evt_002 -> highlight-b2 (replaces b1)

    saved = load_highlight_reinforcement_selections(
        tmp_path / "highlight-reinforcement-selections.json"
    )
    assert set(saved.selections) == {
        HighlightReinforcementSelection(_EVENT_A, "highlight-a1"),
        HighlightReinforcementSelection(_EVENT_B, "highlight-b2"),
    }


def test_update_preserves_a_prior_selection_written_outside_this_session(tmp_path: Path) -> None:
    _create_package(tmp_path)
    write_highlight_reinforcement_selections(
        tmp_path / "highlight-reinforcement-selections.json",
        HighlightReinforcementSelectionSet(
            (HighlightReinforcementSelection(_EVENT_B, "highlight-b1"),)
        ),
    )
    session = PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)

    session.update(review_token="reinforcement-001")  # evt_001 -> highlight-a1

    saved = load_highlight_reinforcement_selections(
        tmp_path / "highlight-reinforcement-selections.json"
    )
    assert set(saved.selections) == {
        HighlightReinforcementSelection(_EVENT_A, "highlight-a1"),
        HighlightReinforcementSelection(_EVENT_B, "highlight-b1"),
    }


# ---------------------------------------------------------------------------
# Fail-closed cases
# ---------------------------------------------------------------------------


def test_from_directory_rejects_missing_conflicts_file(tmp_path: Path) -> None:
    with pytest.raises(PrivateHighlightReinforcementReviewError, match="unavailable"):
        PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)


def test_from_directory_rejects_a_missing_asset(tmp_path: Path) -> None:
    conflicts = _create_package(tmp_path)
    first = conflicts.conflicts[0]
    (tmp_path / first.method.value / f"clip-{first.rank:02d}.mp4").unlink()

    with pytest.raises(PrivateHighlightReinforcementReviewError, match="unavailable"):
        PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)


def test_from_directory_rejects_a_symlinked_conflicts_file(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    _create_package(real_root)
    link_path = tmp_path / "highlight-reinforcement-conflicts.json"
    link_path.symlink_to(real_root / "highlight-reinforcement-conflicts.json")

    with pytest.raises(PrivateHighlightReinforcementReviewError, match="unavailable"):
        PrivateHighlightReinforcementReviewSession.from_directory(tmp_path)


def test_http_api_updates_local_selection_and_serves_only_the_chosen_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY", str(tmp_path))

    status, _, body = _request("/api/private-highlight-reinforcement-review")
    assert status == "200 OK"
    payload = json.loads(body)
    assert payload["review"]["conflict_count"] == 2
    assert str(tmp_path) not in body.decode()

    update_status, _, update_body = _request(
        "/api/private-highlight-reinforcement-review",
        body=json.dumps({"review_token": "reinforcement-001"}).encode(),
        method="POST",
    )
    assert update_status == "200 OK"
    assert json.loads(update_body)["review"]["conflict_count"] == 2

    asset_status, headers, asset_body = _request(
        "/api/private-highlight-reinforcement-review/asset",
        query_string="review_token=reinforcement-001&kind=media",
    )
    assert asset_status == "200 OK"
    assert headers["Content-Type"] == "video/mp4"
    assert asset_body == b"private-video"

    missing_status, _, _ = _request(
        "/api/private-highlight-reinforcement-review/asset",
        query_string="review_token=highlight-a1&kind=media",
    )
    assert missing_status == "404 Not Found"


def test_http_update_rejects_malformed_and_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY", str(tmp_path))

    for body in (
        b"not json",
        json.dumps({"review_token": "reinforcement-001", "extra": "field"}).encode(),
        json.dumps({}).encode(),
        json.dumps({"review_token": 123}).encode(),
    ):
        status, _, response_body = _request(
            "/api/private-highlight-reinforcement-review", body=body, method="POST"
        )
        assert status == "400 Bad Request"
        assert (
            response_body
            == b'{"error":"private highlight reinforcement review request is invalid"}'
        )


def test_http_update_rejects_non_loopback_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY", str(tmp_path))

    status, _, body = _request(
        "/api/private-highlight-reinforcement-review",
        body=json.dumps({"review_token": "reinforcement-001"}).encode(),
        method="POST",
        extra_environ={"HTTP_ORIGIN": "https://example.com"},
    )

    assert status == "400 Bad Request"
    assert body == b'{"error":"private highlight reinforcement review request is invalid"}'
    assert not (tmp_path / "highlight-reinforcement-selections.json").exists()


def test_http_paths_are_disabled_in_public_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY", str(tmp_path))

    for path in (
        "/private-highlight-reinforcement-review",
        "/api/private-highlight-reinforcement-review",
        "/api/private-highlight-reinforcement-review/asset",
    ):
        status, _, body = _request(path)
        assert status == "403 Forbidden"
        assert body == b'{"error":"disabled in public demo mode"}'


def test_page_shows_safe_setup_message_without_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.delenv("RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY", raising=False)

    status, headers, body = _request("/private-highlight-reinforcement-review")
    rendered = body.decode()

    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "RIDE_PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY" in rendered
    assert str(tmp_path) not in rendered
    assert "unavailable" not in rendered
    assert "Traceback" not in rendered


# ---------------------------------------------------------------------------
# Localized UI text
# ---------------------------------------------------------------------------


def test_page_uses_existing_bilingual_ui_conventions() -> None:
    japanese_page = _private_highlight_reinforcement_review_page(UiLanguage.JAPANESE)
    english_page = _private_highlight_reinforcement_review_page(UiLanguage.ENGLISH)

    assert "この画面は、明示設定したローカル確認パッケージだけを読み書きします。" in japanese_page
    assert "This page reads and writes only the explicitly configured local review package." in (
        english_page
    )
    assert "review_token" in japanese_page
    assert "review_token" in english_page
    for page in (japanese_page, english_page):
        assert "event_id" not in page
        assert "candidate_id" not in page
