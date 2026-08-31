"""Persist and evaluate human visual-evidence decisions for local clips."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.edit import CandidateEvidenceStatus

from .catalog import ResolvedCandidateClip, VideoMatchStatus

LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION = "local-evidence-review-v1"


@dataclass(frozen=True)
class LocalEvidenceDecision:
    event_id: str
    evidence_status: CandidateEvidenceStatus
    evidence_source: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("evidence decision event ID is required")
        if self.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE:
            if self.evidence_source is not None:
                raise ValueError("awaiting evidence decision source must be None")
        elif not self.evidence_source or not self.evidence_source.strip():
            raise ValueError("decided evidence requires a non-empty source")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "evidence_status": self.evidence_status.value,
            "evidence_source": self.evidence_source,
        }


@dataclass(frozen=True)
class LocalEvidenceReview:
    decisions: tuple[LocalEvidenceDecision, ...]

    def __post_init__(self) -> None:
        event_ids = [decision.event_id for decision in self.decisions]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("evidence review event IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class LocalEvidenceReviewResult:
    ready_for_render: bool
    confirmed_event_ids: tuple[str, ...]
    awaiting_event_ids: tuple[str, ...]
    rejected_event_ids: tuple[str, ...]
    unmatched_event_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ready_for_render": self.ready_for_render,
            "confirmed_event_ids": list(self.confirmed_event_ids),
            "awaiting_event_ids": list(self.awaiting_event_ids),
            "rejected_event_ids": list(self.rejected_event_ids),
            "unmatched_event_ids": list(self.unmatched_event_ids),
            "reasons": list(self.reasons),
        }


def build_local_evidence_review_template(
    clips: tuple[ResolvedCandidateClip, ...],
) -> LocalEvidenceReview:
    return LocalEvidenceReview(
        tuple(
            LocalEvidenceDecision(
                event_id=clip.event_id,
                evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
            )
            for clip in clips
        )
    )


def evaluate_local_evidence_review(
    clips: tuple[ResolvedCandidateClip, ...],
    review: LocalEvidenceReview,
) -> LocalEvidenceReviewResult:
    clip_event_ids = tuple(clip.event_id for clip in clips)
    decision_event_ids = tuple(decision.event_id for decision in review.decisions)
    if set(clip_event_ids) != set(decision_event_ids):
        raise ValueError("evidence review must contain exactly one decision per candidate clip")
    decisions = {decision.event_id: decision for decision in review.decisions}
    unmatched = tuple(
        clip.event_id for clip in clips if clip.status is not VideoMatchStatus.MATCHED
    )
    invalid_confirmations = tuple(
        event_id
        for event_id in unmatched
        if decisions[event_id].evidence_status is CandidateEvidenceStatus.CONFIRMED
    )
    if invalid_confirmations:
        raise ValueError("an unmatched clip cannot be confirmed as visual evidence")
    confirmed = tuple(
        event_id
        for event_id in clip_event_ids
        if decisions[event_id].evidence_status is CandidateEvidenceStatus.CONFIRMED
    )
    awaiting = tuple(
        event_id
        for event_id in clip_event_ids
        if decisions[event_id].evidence_status
        is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
    )
    rejected = tuple(
        event_id
        for event_id in clip_event_ids
        if decisions[event_id].evidence_status is CandidateEvidenceStatus.REJECTED
    )
    reasons: list[str] = []
    if unmatched:
        reasons.append("timestamp_unmatched_clips")
    if awaiting:
        reasons.append("visual_evidence_awaiting")
    if rejected:
        reasons.append("visual_evidence_rejected")
    return LocalEvidenceReviewResult(
        ready_for_render=not reasons,
        confirmed_event_ids=confirmed,
        awaiting_event_ids=awaiting,
        rejected_event_ids=rejected,
        unmatched_event_ids=unmatched,
        reasons=tuple(reasons),
    )


def load_local_evidence_review(path: Path) -> LocalEvidenceReview:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported local evidence review schema")
    return LocalEvidenceReview(
        tuple(
            LocalEvidenceDecision(
                event_id=item["event_id"],
                evidence_status=CandidateEvidenceStatus(item["evidence_status"]),
                evidence_source=item.get("evidence_source"),
            )
            for item in payload.get("decisions", [])
        )
    )


def write_local_evidence_review(
    output_path: Path,
    review: LocalEvidenceReview,
    *,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "evidence review already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
