"""Tests for the loopback-only private visual-evidence review workflow."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from app.edit import CandidateEvidenceStatus
from app.video import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    LocalReviewClip,
    ResolvedCandidateClip,
    VideoMatchStatus,
    export_candidate_json,
    load_local_evidence_review,
    write_local_evidence_review,
    write_local_review_clip_manifest,
)
from app.web.i18n import UiLanguage
from app.web.private_evidence_review import PrivateEvidenceReviewSession
from app.web.server import _private_evidence_review_page, application


def _clip(event_id: str, asset_id: str) -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id=asset_id,
        file_name=f"private-{event_id}.mp4",
        start_offset_s=0.0,
        end_offset_s=5.0,
        reason="test",
    )


def _create_package(root: Path) -> tuple[ResolvedCandidateClip, ...]:
    clips = (
        _clip("event-private-alpha", "asset-private-alpha"),
        _clip("event-private-beta", "asset-private-beta"),
    )
    (root / "ride-storyteller-candidates.json").write_text(
        export_candidate_json(clips), encoding="utf-8"
    )
    write_local_evidence_review(
        root / "evidence-review.json",
        LocalEvidenceReview(
            tuple(
                LocalEvidenceDecision(
                    event_id=clip.event_id,
                    evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
                )
                for clip in clips
            )
        ),
    )
    manifest = tuple(
        LocalReviewClip(
            event_id=clip.event_id,
            asset_id=clip.asset_id or "",
            output_file_name=f"review-{index:03d}.mp4",
            duration_s=5.0,
        )
        for index, clip in enumerate(clips, start=1)
    )
    write_local_review_clip_manifest(root / "review-clip-manifest.json", manifest)
    review_root = root / "review-clips"
    review_root.mkdir()
    for item in manifest:
        (review_root / item.output_file_name).write_bytes(b"private-video")
    return clips


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


def test_private_evidence_payload_exposes_only_opaque_review_ids(tmp_path: Path) -> None:
    _create_package(tmp_path)

    payload = PrivateEvidenceReviewSession.from_directory(tmp_path).payload()
    serialized = json.dumps(payload)

    assert payload["local_only"] is True
    assert payload["external_data_sent"] is False
    assert "event-private" not in serialized
    assert "asset-private" not in serialized
    assert "private-alpha.mp4" not in serialized
    assert str(tmp_path) not in serialized
    assert "/api/private-evidence-review/asset?review_id=review-001" in serialized
    assert payload["next_gate"] == "human_visual_evidence_review"


def test_private_evidence_update_persists_only_the_selected_human_decision(
    tmp_path: Path,
) -> None:
    clips = _create_package(tmp_path)
    session = PrivateEvidenceReviewSession.from_directory(tmp_path)

    payload = session.update(
        review_id="review-001",
        status=CandidateEvidenceStatus.CONFIRMED,
    )

    candidates = payload["review"]["candidates"]  # type: ignore[index]
    assert candidates[0]["status"] == "confirmed"  # type: ignore[index]
    assert candidates[1]["status"] == "awaiting_video_evidence"  # type: ignore[index]
    review = load_local_evidence_review(tmp_path / "evidence-review.json")
    decisions = {decision.event_id: decision for decision in review.decisions}
    assert decisions[clips[0].event_id].evidence_source == "human_local_review"
    assert decisions[clips[1].event_id].evidence_source is None


def test_private_evidence_next_gate_requires_replacement_before_remaining_review(
    tmp_path: Path,
) -> None:
    _create_package(tmp_path)
    session = PrivateEvidenceReviewSession.from_directory(tmp_path)

    payload = session.update(
        review_id="review-001",
        status=CandidateEvidenceStatus.REJECTED,
    )

    assert payload["next_gate"] == "replace_rejected_candidate_clips"


def test_private_evidence_next_gate_requires_pipeline_revalidation_after_confirmation(
    tmp_path: Path,
) -> None:
    _create_package(tmp_path)
    session = PrivateEvidenceReviewSession.from_directory(tmp_path)
    session.update(review_id="review-001", status=CandidateEvidenceStatus.CONFIRMED)

    payload = session.update(
        review_id="review-002",
        status=CandidateEvidenceStatus.CONFIRMED,
    )

    assert payload["next_gate"] == "revalidate_local_pipeline"


def test_private_evidence_session_rejects_unknown_review_id_and_missing_asset(
    tmp_path: Path,
) -> None:
    _create_package(tmp_path)
    session = PrivateEvidenceReviewSession.from_directory(tmp_path)

    with pytest.raises(Exception, match="unknown"):
        session.update(
            review_id="review-999",
            status=CandidateEvidenceStatus.CONFIRMED,
        )
    (tmp_path / "review-clips" / "review-001.mp4").unlink()
    with pytest.raises(Exception, match="unavailable"):
        PrivateEvidenceReviewSession.from_directory(tmp_path)


def test_private_evidence_http_api_updates_and_serves_only_selected_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY", str(tmp_path))

    status, _, body = _request("/api/private-evidence-review")
    payload = json.loads(body)
    assert status == "200 OK"
    assert payload["review"]["status_counts"]["awaiting_video_evidence"] == 2
    assert str(tmp_path) not in body.decode()

    update = json.dumps({"review_id": "review-001", "status": "rejected"}).encode()
    update_status, _, update_body = _request(
        "/api/private-evidence-review", body=update, method="POST"
    )
    assert update_status == "200 OK"
    assert json.loads(update_body)["review"]["status_counts"]["rejected"] == 1

    asset_status, headers, asset_body = _request(
        "/api/private-evidence-review/asset",
        query_string="review_id=review-001",
    )
    assert asset_status == "200 OK"
    assert headers["Content-Type"] == "video/mp4"
    assert asset_body == b"private-video"


def test_private_evidence_http_paths_are_disabled_in_public_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    monkeypatch.setenv("RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY", str(tmp_path))

    for path in (
        "/private-evidence-review",
        "/api/private-evidence-review",
        "/api/private-evidence-review/asset",
    ):
        status, _, body = _request(path)
        assert status == "403 Forbidden"
        assert body == b'{"error":"disabled in public demo mode"}'


def test_private_evidence_page_updates_one_card_without_repainting_unsaved_cards() -> None:
    page = _private_evidence_review_page(UiLanguage.JAPANESE)

    assert "render(await response.json())" not in page
    assert "updatedCandidate=payload.review.candidates.find" in page
    assert "candidate.status=updatedCandidate.status" in page
    assert "cards.replaceChildren" in page
    assert "gateLabels[nextGate]" in page


def test_private_evidence_http_update_rejects_non_loopback_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_package(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "local")
    monkeypatch.setenv("RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY", str(tmp_path))
    body = json.dumps({"review_id": "review-001", "status": "confirmed"}).encode()
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    response = b"".join(
        application(
            {
                "PATH_INFO": "/api/private-evidence-review",
                "QUERY_STRING": "",
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": str(len(body)),
                "HTTP_ORIGIN": "https://example.com",
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )
    )
    assert captured["status"] == "400 Bad Request"
    assert response == b'{"error":"private evidence review request is invalid"}'
