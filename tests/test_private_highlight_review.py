import json
from io import BytesIO
from pathlib import Path

import pytest

import app.web.server as web_server
from app.video.highlight_quality import QualitySelectionMethod
from app.video.highlight_review import (
    HighlightReview,
    HighlightReviewDecision,
    HighlightReviewReason,
    HighlightReviewStatus,
    write_highlight_review,
)
from app.web.private_highlight_review import PrivateHighlightReviewSession
from app.web.server import (
    _private_highlight_review_page,
    _private_review_origin_is_local,
    application,
)


def _create_package(root: Path) -> HighlightReview:
    decisions = (
        HighlightReviewDecision(
            "highlight-alpha",
            QualitySelectionMethod.QUALITY_FIRST,
            1,
            HighlightReviewStatus.AWAITING,
        ),
        HighlightReviewDecision(
            "highlight-beta",
            QualitySelectionMethod.RIDE_DYNAMICS,
            1,
            HighlightReviewStatus.AWAITING,
        ),
    )
    review = HighlightReview(decisions)
    for decision in decisions:
        (root / decision.method.value).mkdir(parents=True, exist_ok=True)
        (root / decision.method.value / f"clip-{decision.rank:02d}.mp4").write_bytes(
            b"private-video"
        )
    thumbnail_root = root / "review-thumbnails"
    thumbnail_root.mkdir(parents=True)
    for decision in decisions:
        (thumbnail_root / f"{decision.method.value}-clip-{decision.rank:02d}.jpg").write_bytes(
            b"private-thumbnail"
        )
    write_highlight_review(root / "highlight-review.json", review)
    return review


def _request(
    path: str,
    *,
    body: bytes = b"",
    method: str = "GET",
    query_string: str = "",
) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    response = b"".join(
        application(
            {
                "PATH_INFO": path,
                "QUERY_STRING": query_string,
                "REQUEST_METHOD": method,
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )
    )
    return captured["status"], captured["headers"], response  # type: ignore[return-value]


def test_private_session_exposes_only_opaque_ids_and_server_owned_urls(tmp_path: Path) -> None:
    _create_package(tmp_path)

    payload = PrivateHighlightReviewSession.from_directory(tmp_path).payload()
    serialized = json.dumps(payload)

    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False
    assert "private-video" not in serialized
    assert str(tmp_path) not in serialized
    assert "/api/private-highlight-review/asset?candidate_id=highlight-alpha" in serialized


def test_private_session_updates_only_the_selected_fixed_vocabulary_decision(
    tmp_path: Path,
) -> None:
    review = _create_package(tmp_path)
    session = PrivateHighlightReviewSession.from_directory(tmp_path)

    payload = session.update(
        candidate_id=review.decisions[0].candidate_id,
        status=HighlightReviewStatus.APPROVED,
        reasons=(HighlightReviewReason.CLEAR_TURN,),
    )

    decisions = payload["review"]["candidates"]  # type: ignore[index]
    assert decisions[0]["status"] == "approved"  # type: ignore[index]
    assert decisions[0]["reasons"] == ["clear_turn"]  # type: ignore[index]
    assert decisions[1]["status"] == "awaiting"  # type: ignore[index]


def test_private_session_rejects_unknown_candidate_and_missing_assets(tmp_path: Path) -> None:
    review = _create_package(tmp_path)
    session = PrivateHighlightReviewSession.from_directory(tmp_path)

    with pytest.raises(ValueError, match="unknown"):
        session.update(
            candidate_id="highlight-unknown",
            status=HighlightReviewStatus.AWAITING,
            reasons=(),
        )
    (tmp_path / review.decisions[0].method.value / "clip-01.mp4").unlink()
    with pytest.raises(Exception, match="unavailable"):
        PrivateHighlightReviewSession.from_directory(tmp_path)


def test_private_review_http_api_updates_local_review_and_serves_only_selected_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY", str(tmp_path))

    status, _, body = _request("/api/private-highlight-review")
    payload = json.loads(body)
    assert status == "200 OK"
    assert payload["review"]["status_counts"]["awaiting"] == 2
    assert str(tmp_path) not in body.decode()

    update = json.dumps(
        {
            "candidate_id": review.decisions[0].candidate_id,
            "status": "rejected",
            "reasons": ["too_straight"],
        }
    ).encode()
    update_status, _, update_body = _request(
        "/api/private-highlight-review", body=update, method="POST"
    )
    assert update_status == "200 OK"
    assert json.loads(update_body)["review"]["status_counts"]["rejected"] == 1

    asset_status, headers, asset_body = _request(
        "/api/private-highlight-review/asset",
        query_string="candidate_id=highlight-alpha&kind=media",
    )
    assert asset_status == "200 OK"
    assert headers["Content-Type"] == "video/mp4"
    assert asset_body == b"private-video"

    missing_status, _, _ = _request(
        "/api/private-highlight-review/asset",
        query_string="candidate_id=unknown&kind=media",
    )
    assert missing_status == "404 Not Found"


def test_private_review_http_paths_are_disabled_in_public_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    monkeypatch.setenv("RIDE_PRIVATE_HIGHLIGHT_REVIEW_DIRECTORY", str(tmp_path))

    for path in (
        "/private-highlight-review",
        "/api/private-highlight-review",
        "/api/private-highlight-review/asset",
    ):
        status, _, body = _request(path)
        assert status == "403 Forbidden"
        assert body == b'{"error":"disabled in public demo mode"}'


def test_private_review_rejects_non_loopback_browser_origins_and_localizes_reasons() -> None:
    assert _private_review_origin_is_local({"HTTP_ORIGIN": "http://127.0.0.1:8766"})
    assert _private_review_origin_is_local({})
    assert not _private_review_origin_is_local({"HTTP_ORIGIN": "https://example.com"})

    japanese_page = _private_highlight_review_page(web_server.UiLanguage.JAPANESE)
    english_page = _private_highlight_review_page(web_server.UiLanguage.ENGLISH)
    assert "明確な旋回" in japanese_page
    assert "clear turn" in english_page


def test_private_review_saves_one_card_without_repainting_unsaved_cards() -> None:
    page = _private_highlight_review_page(web_server.UiLanguage.JAPANESE)

    assert "render(await response.json())" not in page
    assert "updatedCandidate=payload.review.candidates.find" in page
    assert "candidate.status=updatedCandidate.status" in page
    assert "cards.replaceChildren" in page
