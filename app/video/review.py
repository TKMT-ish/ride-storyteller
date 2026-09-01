"""Decide and persist visual-evidence decisions for local clips.

As of 2026-09-01, the only required human confirmation in the local pipeline is
the camera-to-GPS clock offset (see `local_catalog.clock_offset_confirmed`).
`auto_decide_local_evidence_review` therefore decides every candidate clip
automatically: a timestamp-matched clip is confirmed, and a clip with no
matching video is rejected, using a fixed, non-identifying source marker
either way. A rejected or unmatched event simply drops out of the story; it no
longer blocks rendering by itself (see `evaluate_local_evidence_review`). The
lower-level manual template and the human-review web UI
(`app/web/private_evidence_review.py`) remain available for optional
correction.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp

from app.edit import CandidateEvidenceStatus

from .catalog import ResolvedCandidateClip, VideoMatchStatus

LOCAL_EVIDENCE_REVIEW_SCHEMA_VERSION = "local-evidence-review-v1"

# Fixed, non-identifying evidence_source markers used by the automatic
# decision. They never carry a file name, asset ID, or timestamp.
AUTO_DECIDED_MATCHED_SOURCE = "auto_decided_timestamp_matched"
AUTO_DECIDED_UNMATCHED_SOURCE = "auto_decided_no_matching_video"


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
    # Per the 2026-09-01 decision (current-system-handoff-ja.md §5), an event
    # with no matching video, or an explicitly rejected one, simply drops out
    # of the story rather than blocking the whole render. Only an outstanding
    # awaiting decision, or having nothing confirmed at all, blocks it.
    ready_for_render = not awaiting and bool(confirmed)
    return LocalEvidenceReviewResult(
        ready_for_render=ready_for_render,
        confirmed_event_ids=confirmed,
        awaiting_event_ids=awaiting,
        rejected_event_ids=rejected,
        unmatched_event_ids=unmatched,
        reasons=tuple(reasons),
    )


def auto_decide_local_evidence_review(
    clips: tuple[ResolvedCandidateClip, ...],
) -> LocalEvidenceReview:
    """Decide every candidate clip automatically from timestamp matching alone.

    This is the sole decision step once the one required human confirmation
    (camera-to-GPS clock offset) is in place; no per-clip human confirmation is
    requested. A matched clip is confirmed; an unmatched clip is rejected so it
    drops out of the story instead of leaving the pipeline waiting on a human.
    Neither outcome reveals a source path, file name, or timestamp.
    """
    return LocalEvidenceReview(
        tuple(
            LocalEvidenceDecision(
                event_id=clip.event_id,
                evidence_status=(
                    CandidateEvidenceStatus.CONFIRMED
                    if clip.status is VideoMatchStatus.MATCHED
                    else CandidateEvidenceStatus.REJECTED
                ),
                evidence_source=(
                    AUTO_DECIDED_MATCHED_SOURCE
                    if clip.status is VideoMatchStatus.MATCHED
                    else AUTO_DECIDED_UNMATCHED_SOURCE
                ),
            )
            for clip in clips
        )
    )


def load_or_autodecide_local_evidence_review(
    path: Path,
    clips: tuple[ResolvedCandidateClip, ...],
) -> LocalEvidenceReview:
    """Preserve a prior review (including any manual correction) or auto-decide.

    A prior file may hold either an old awaiting/human-reviewed file or a
    previous automatic decision; either is kept as-is so a human's manual
    correction survives a rerun. Only a missing file triggers a fresh
    automatic decision.
    """
    if path.exists():
        review = load_local_evidence_review(path)
        evaluate_local_evidence_review(clips, review)
        return review
    review = auto_decide_local_evidence_review(clips)
    write_local_evidence_review(path, review)
    return review


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
    file_descriptor, temporary_name = mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(review.to_dict(), ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path
