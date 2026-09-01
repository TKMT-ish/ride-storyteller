from dataclasses import replace
from pathlib import Path

import pytest

import app.video.review as review_module
from app.edit import CandidateEvidenceStatus
from app.video import ResolvedCandidateClip, VideoMatchStatus
from app.video.review import (
    LocalEvidenceDecision,
    LocalEvidenceReview,
    build_local_evidence_review_template,
    evaluate_local_evidence_review,
    load_local_evidence_review,
    write_local_evidence_review,
)


def _clip(event_id: str = "event_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id="asset_001",
        file_name="source.mp4",
        start_offset_s=0.0,
        end_offset_s=10.0,
        reason="test",
    )


def test_evidence_template_starts_every_candidate_awaiting() -> None:
    review = build_local_evidence_review_template((_clip(), _clip("event_002")))

    assert all(
        decision.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
        for decision in review.decisions
    )
    assert all(decision.evidence_source is None for decision in review.decisions)


def test_evidence_review_is_ready_only_when_every_clip_is_confirmed() -> None:
    clips = (_clip(), _clip("event_002"))
    review = LocalEvidenceReview(
        tuple(
            LocalEvidenceDecision(
                clip.event_id,
                CandidateEvidenceStatus.CONFIRMED,
                "human_review",
            )
            for clip in clips
        )
    )

    result = evaluate_local_evidence_review(clips, review)

    assert result.ready_for_render
    assert result.confirmed_event_ids == ("event_001", "event_002")
    assert result.reasons == ()


def test_evidence_review_separates_awaiting_rejected_and_unmatched() -> None:
    clips = (
        _clip(),
        _clip("event_002"),
        replace(
            _clip("event_003"),
            status=VideoMatchStatus.NOT_FOUND,
            asset_id=None,
            file_name=None,
            start_offset_s=None,
            end_offset_s=None,
        ),
    )
    review = LocalEvidenceReview(
        (
            LocalEvidenceDecision(
                "event_001", CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
            ),
            LocalEvidenceDecision(
                "event_002", CandidateEvidenceStatus.REJECTED, "human_review"
            ),
            LocalEvidenceDecision(
                "event_003", CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
            ),
        )
    )

    result = evaluate_local_evidence_review(clips, review)

    assert not result.ready_for_render
    assert result.awaiting_event_ids == ("event_001", "event_003")
    assert result.rejected_event_ids == ("event_002",)
    assert result.unmatched_event_ids == ("event_003",)
    assert result.reasons == (
        "timestamp_unmatched_clips",
        "visual_evidence_awaiting",
        "visual_evidence_rejected",
    )


def test_evidence_review_rejects_confirmation_for_unmatched_clip() -> None:
    clip = replace(
        _clip(),
        status=VideoMatchStatus.NOT_FOUND,
        asset_id=None,
        file_name=None,
        start_offset_s=None,
        end_offset_s=None,
    )
    review = LocalEvidenceReview(
        (
            LocalEvidenceDecision(
                "event_001", CandidateEvidenceStatus.CONFIRMED, "human_review"
            ),
        )
    )

    with pytest.raises(ValueError, match="unmatched clip cannot be confirmed"):
        evaluate_local_evidence_review((clip,), review)


def test_evidence_review_requires_exact_candidate_event_set() -> None:
    review = LocalEvidenceReview(
        (
            LocalEvidenceDecision(
                "other", CandidateEvidenceStatus.CONFIRMED, "human_review"
            ),
        )
    )

    with pytest.raises(ValueError, match="exactly one decision"):
        evaluate_local_evidence_review((_clip(),), review)


def test_evidence_review_round_trip_and_overwrite_guard(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "evidence-review.json"
    review = build_local_evidence_review_template((_clip(),))

    assert write_local_evidence_review(path, review) == path
    assert load_local_evidence_review(path) == review
    with pytest.raises(FileExistsError, match="already exists"):
        write_local_evidence_review(path, review)
    assert write_local_evidence_review(path, review, overwrite=True) == path


def test_evidence_review_atomic_write_preserves_existing_decision_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "evidence-review.json"
    original = build_local_evidence_review_template((_clip(),))
    replacement = LocalEvidenceReview(
        (
            LocalEvidenceDecision(
                "event_001", CandidateEvidenceStatus.CONFIRMED, "human_review"
            ),
        )
    )
    write_local_evidence_review(path, original)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(review_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_local_evidence_review(path, replacement, overwrite=True)

    assert load_local_evidence_review(path) == original
    assert not tuple(tmp_path.glob(".evidence-review.json.*.tmp"))


def test_evidence_decision_invariants() -> None:
    with pytest.raises(ValueError, match="source must be None"):
        LocalEvidenceDecision(
            "event_001",
            CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
            "human_review",
        )
    with pytest.raises(ValueError, match="non-empty source"):
        LocalEvidenceDecision("event_001", CandidateEvidenceStatus.CONFIRMED, "   ")
