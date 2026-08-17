"""Create a reviewable candidate-clip plan without claiming an edit is ready."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.contracts import GpsEvent, StoryPlan


class CandidateEvidenceStatus(StrEnum):
    """Evidence status for a proposed clip, separate from its GPS rationale."""

    AWAITING_VIDEO_EVIDENCE = "awaiting_video_evidence"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class CandidatePlanStatus(StrEnum):
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"


@dataclass(frozen=True)
class CandidateClip:
    chapter_id: str
    event_id: str
    asset_name_hint: str
    start_offset_s: float
    end_offset_s: float
    requested_duration_s: float
    evidence_status: CandidateEvidenceStatus
    evidence_source: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE:
            if self.evidence_source is not None:
                raise ValueError(
                    "evidence_source must be None when status is awaiting_video_evidence"
                )
        else:
            if not self.evidence_source or not self.evidence_source.strip():
                raise ValueError(
                    "evidence_source must be a non-empty, non-whitespace string "
                    "when status is confirmed or rejected"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "chapter_id": self.chapter_id,
            "event_id": self.event_id,
            "asset_name_hint": self.asset_name_hint,
            "start_offset_s": self.start_offset_s,
            "end_offset_s": self.end_offset_s,
            "requested_duration_s": self.requested_duration_s,
            "evidence_status": self.evidence_status.value,
            "evidence_source": self.evidence_source,
        }


@dataclass(frozen=True)
class CandidateEditPlan:
    story_title: str
    target_duration_s: float
    candidate_duration_s: float
    coverage_ratio: float
    status: CandidatePlanStatus
    clips: tuple[CandidateClip, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "story_title": self.story_title,
            "target_duration_s": self.target_duration_s,
            "candidate_duration_s": self.candidate_duration_s,
            "coverage_ratio": self.coverage_ratio,
            "status": self.status.value,
            "clips": [clip.to_dict() for clip in self.clips],
        }


@dataclass(frozen=True)
class CandidateEditReview:
    is_ready_for_edit: bool
    missing_duration_s: float
    reasons: tuple[str, ...]
    event_ids_requiring_evidence: tuple[str, ...]
    rejected_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "is_ready_for_edit": self.is_ready_for_edit,
            "missing_duration_s": self.missing_duration_s,
            "reasons": list(self.reasons),
            "event_ids_requiring_evidence": list(self.event_ids_requiring_evidence),
            "rejected_event_ids": list(self.rejected_event_ids),
        }


def build_candidate_edit_plan(
    story_plan: StoryPlan, events: tuple[GpsEvent, ...]
) -> CandidateEditPlan:
    """Map selected GPS events to clip requests; never infer visual suitability."""
    events_by_id = {event.event_id: event for event in events}
    clips: list[CandidateClip] = []
    for chapter in story_plan.chapters:
        event = events_by_id.get(chapter.event_id)
        if event is None:
            raise ValueError(f"story plan event is missing: {chapter.event_id}")
        query = event.video_query
        requested_duration_s = query.clip_end_offset_s - query.clip_start_offset_s
        clips.append(
            CandidateClip(
                chapter_id=chapter.chapter_id,
                event_id=event.event_id,
                asset_name_hint=query.asset_name_hint,
                start_offset_s=query.clip_start_offset_s,
                end_offset_s=query.clip_end_offset_s,
                requested_duration_s=requested_duration_s,
                evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
            )
        )
    candidate_duration_s = sum(clip.requested_duration_s for clip in clips)
    coverage_ratio = candidate_duration_s / story_plan.target_duration_s
    return CandidateEditPlan(
        story_title=story_plan.title,
        target_duration_s=story_plan.target_duration_s,
        candidate_duration_s=candidate_duration_s,
        coverage_ratio=coverage_ratio,
        status=CandidatePlanStatus.NEEDS_MORE_EVIDENCE,
        clips=tuple(clips),
    )


def review_candidate_edit_plan(plan: CandidateEditPlan) -> CandidateEditReview:
    """Fail closed until duration and visual evidence have both been confirmed."""
    missing_duration_s = max(0.0, plan.target_duration_s - plan.candidate_duration_s)
    pending_event_ids = tuple(
        clip.event_id
        for clip in plan.clips
        if clip.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
    )
    rejected_event_ids = tuple(
        clip.event_id
        for clip in plan.clips
        if clip.evidence_status is CandidateEvidenceStatus.REJECTED
    )
    reasons: list[str] = []
    if missing_duration_s > 0:
        reasons.append("目標尺を満たす候補クリップが不足しています。")
    if pending_event_ids:
        reasons.append("候補クリップの映像証拠が未確認です。")
    if rejected_event_ids:
        reasons.append("映像証拠が不適切と判定された候補クリップがあります。差し替えが必要です。")
    return CandidateEditReview(
        is_ready_for_edit=not reasons,
        missing_duration_s=missing_duration_s,
        reasons=tuple(reasons),
        event_ids_requiring_evidence=pending_event_ids,
        rejected_event_ids=rejected_event_ids,
    )


def confirm_clip_evidence(
    clip: CandidateClip,
    *,
    confirmed: bool,
    source: str,
) -> CandidateClip:
    """Return a new clip with evidence status set to CONFIRMED or REJECTED.

    Only transitions from AWAITING_VIDEO_EVIDENCE are permitted; calling on an
    already-decided clip raises ValueError to prevent silent re-decisions.
    source must be a non-empty, non-whitespace string naming what triggered the
    update (for example ``"human_review"`` or ``"video_analysis"``).
    """
    if not source or not source.strip():
        raise ValueError("source must be a non-empty, non-whitespace string")
    if clip.evidence_status is not CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE:
        raise ValueError(
            f"clip {clip.event_id!r} evidence status is already "
            f"{clip.evidence_status.value!r}; only awaiting clips may be updated"
        )
    new_status = (
        CandidateEvidenceStatus.CONFIRMED if confirmed else CandidateEvidenceStatus.REJECTED
    )
    return CandidateClip(
        chapter_id=clip.chapter_id,
        event_id=clip.event_id,
        asset_name_hint=clip.asset_name_hint,
        start_offset_s=clip.start_offset_s,
        end_offset_s=clip.end_offset_s,
        requested_duration_s=clip.requested_duration_s,
        evidence_status=new_status,
        evidence_source=source,
    )


def confirmed_event_ids(plan: CandidateEditPlan) -> tuple[str, ...]:
    """Return event IDs of clips whose evidence status is CONFIRMED."""
    return tuple(
        clip.event_id
        for clip in plan.clips
        if clip.evidence_status is CandidateEvidenceStatus.CONFIRMED
    )
