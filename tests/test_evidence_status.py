"""Tests for the CandidateClip evidence-status lifecycle."""

import pytest

from app.edit import (
    CandidateEditPlan,
    CandidateEvidenceStatus,
    build_ffmpeg_render_plan,
    confirm_clip_evidence,
    confirmed_event_ids,
    review_candidate_edit_plan,
)
from app.edit.candidate_planner import CandidateClip, CandidatePlanStatus
from app.video import ResolvedCandidateClip, VideoMatchStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _awaiting_clip(event_id: str = "evt_001", duration_s: float = 30.0) -> CandidateClip:
    return CandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        asset_name_hint="ride.mp4",
        start_offset_s=0.0,
        end_offset_s=duration_s,
        requested_duration_s=duration_s,
        evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
    )


def _plan(*clips: CandidateClip, target_duration_s: float = 480.0) -> CandidateEditPlan:
    candidate_duration_s = sum(c.requested_duration_s for c in clips)
    return CandidateEditPlan(
        story_title="テスト旅",
        target_duration_s=target_duration_s,
        candidate_duration_s=candidate_duration_s,
        coverage_ratio=candidate_duration_s / target_duration_s,
        status=CandidatePlanStatus.NEEDS_MORE_EVIDENCE,
        clips=clips,
    )


def _resolved_clip(event_id: str = "evt_001") -> ResolvedCandidateClip:
    return ResolvedCandidateClip(
        chapter_id="chapter_01",
        event_id=event_id,
        status=VideoMatchStatus.MATCHED,
        asset_id="gopro_001",
        file_name="GX010001.MP4",
        start_offset_s=0.0,
        end_offset_s=30.0,
        reason="test",
    )


# ---------------------------------------------------------------------------
# 1. confirm_clip_evidence — happy paths
# ---------------------------------------------------------------------------

def test_confirm_clip_sets_status_and_stores_source() -> None:
    clip = _awaiting_clip()
    result = confirm_clip_evidence(clip, confirmed=True, source="human_review")

    assert result.evidence_status is CandidateEvidenceStatus.CONFIRMED
    assert result.evidence_source == "human_review"
    d = result.to_dict()
    assert d["evidence_status"] == "confirmed"
    assert d["evidence_source"] == "human_review"


def test_reject_clip_sets_status_and_stores_source() -> None:
    clip = _awaiting_clip()
    result = confirm_clip_evidence(clip, confirmed=False, source="video_analysis")

    assert result.evidence_status is CandidateEvidenceStatus.REJECTED
    assert result.evidence_source == "video_analysis"
    d = result.to_dict()
    assert d["evidence_status"] == "rejected"
    assert d["evidence_source"] == "video_analysis"


def test_new_clip_has_no_evidence_source() -> None:
    clip = _awaiting_clip()

    assert clip.evidence_source is None
    assert clip.to_dict()["evidence_source"] is None


# ---------------------------------------------------------------------------
# 2. confirm_clip_evidence — guard rails
# ---------------------------------------------------------------------------

def test_confirm_already_confirmed_raises() -> None:
    confirmed = confirm_clip_evidence(_awaiting_clip(), confirmed=True, source="human_review")

    with pytest.raises(ValueError, match="already"):
        confirm_clip_evidence(confirmed, confirmed=True, source="human_review")


def test_confirm_already_rejected_raises() -> None:
    rejected = confirm_clip_evidence(_awaiting_clip(), confirmed=False, source="video_analysis")

    with pytest.raises(ValueError, match="already"):
        confirm_clip_evidence(rejected, confirmed=True, source="human_review")


def test_confirm_requires_nonempty_source() -> None:
    clip = _awaiting_clip()

    with pytest.raises(ValueError, match="non-empty"):
        confirm_clip_evidence(clip, confirmed=True, source="")


def test_confirm_rejects_whitespace_only_source() -> None:
    clip = _awaiting_clip()

    with pytest.raises(ValueError, match="non-empty"):
        confirm_clip_evidence(clip, confirmed=True, source="   ")


# ---------------------------------------------------------------------------
# 3. confirmed_event_ids
# ---------------------------------------------------------------------------

def test_confirmed_event_ids_returns_only_confirmed() -> None:
    confirmed = confirm_clip_evidence(
        _awaiting_clip("evt_001"), confirmed=True, source="human_review"
    )
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_002"), confirmed=False, source="video_analysis"
    )
    awaiting = _awaiting_clip("evt_003")

    plan = _plan(confirmed, rejected, awaiting)
    ids = confirmed_event_ids(plan)

    assert ids == ("evt_001",)


# ---------------------------------------------------------------------------
# 4. review_candidate_edit_plan — evidence-status separation
# ---------------------------------------------------------------------------

def test_review_separates_awaiting_from_rejected_reasons() -> None:
    awaiting = _awaiting_clip("evt_awaiting")
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_rejected"), confirmed=False, source="video_analysis"
    )

    review = review_candidate_edit_plan(_plan(awaiting, rejected))

    reasons = " ".join(review.reasons)
    assert "未確認" in reasons
    assert "差し替え" in reasons
    assert review.event_ids_requiring_evidence == ("evt_awaiting",)
    assert review.rejected_event_ids == ("evt_rejected",)
    assert not review.is_ready_for_edit


def test_review_rejected_only_has_replacement_reason_not_unconfirmed_reason() -> None:
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_001"), confirmed=False, source="video_analysis"
    )

    review = review_candidate_edit_plan(_plan(rejected))

    reasons = " ".join(review.reasons)
    assert "差し替え" in reasons
    assert "未確認" not in reasons
    assert review.event_ids_requiring_evidence == ()
    assert review.rejected_event_ids == ("evt_001",)
    assert not review.is_ready_for_edit


def test_review_all_confirmed_is_ready() -> None:
    # Build a plan whose candidate_duration_s equals target_duration_s so the
    # duration gate does not block the review independently of evidence status.
    target = 480.0
    confirmed = confirm_clip_evidence(
        _awaiting_clip("evt_001", duration_s=target),
        confirmed=True,
        source="human_review",
    )
    plan = _plan(confirmed, target_duration_s=target)

    review = review_candidate_edit_plan(plan)

    assert review.is_ready_for_edit
    assert review.reasons == ()
    assert review.event_ids_requiring_evidence == ()
    assert review.rejected_event_ids == ()


def test_review_ready_when_confirmed_meets_target_despite_a_rejected_clip() -> None:
    """Per the 2026-09-01 decision, a rejected clip drops out but does not block."""
    target = 30.0
    confirmed = confirm_clip_evidence(
        _awaiting_clip("evt_001", duration_s=target), confirmed=True, source="human_review"
    )
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_002", duration_s=10.0), confirmed=False, source="video_analysis"
    )
    plan = _plan(confirmed, rejected, target_duration_s=target)

    review = review_candidate_edit_plan(plan)

    assert review.is_ready_for_edit
    assert review.rejected_event_ids == ("evt_002",)
    assert "差し替え" in " ".join(review.reasons)


def test_review_not_ready_when_nothing_is_confirmed_even_if_duration_looks_satisfied() -> None:
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_001", duration_s=480.0), confirmed=False, source="video_analysis"
    )
    plan = _plan(rejected, target_duration_s=480.0)

    review = review_candidate_edit_plan(plan)

    assert not review.is_ready_for_edit


def test_review_to_dict_includes_rejected_event_ids() -> None:
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_001"), confirmed=False, source="video_analysis"
    )
    review = review_candidate_edit_plan(_plan(rejected))

    d = review.to_dict()

    assert "rejected_event_ids" in d
    assert d["rejected_event_ids"] == ["evt_001"]


# ---------------------------------------------------------------------------
# 5. Render-plan integration via confirmed_event_ids()
# ---------------------------------------------------------------------------

def test_render_plan_blocked_by_rejected_evidence() -> None:
    rejected = confirm_clip_evidence(
        _awaiting_clip("evt_001"), confirmed=False, source="video_analysis"
    )
    plan = _plan(rejected)

    result = build_ffmpeg_render_plan(
        (_resolved_clip("evt_001"),),
        visual_evidence_confirmed_event_ids=confirmed_event_ids(plan),
    )

    assert result.status.value == "needs_human_review"
    assert result.command is None


def test_render_plan_ready_when_all_confirmed() -> None:
    confirmed = confirm_clip_evidence(
        _awaiting_clip("evt_001"), confirmed=True, source="human_review"
    )
    plan = _plan(confirmed)

    result = build_ffmpeg_render_plan(
        (_resolved_clip("evt_001"),),
        visual_evidence_confirmed_event_ids=confirmed_event_ids(plan),
    )

    assert result.status.value == "ready_for_ffmpeg"
    assert result.command is not None
    assert result.command[0] == "ffmpeg"


# ---------------------------------------------------------------------------
# 6. CandidateClip.__post_init__ direct-construction validation
# ---------------------------------------------------------------------------

def test_direct_construction_confirmed_without_source_raises() -> None:
    with pytest.raises(ValueError, match="non-empty, non-whitespace"):
        CandidateClip(
            chapter_id="chapter_01",
            event_id="evt_001",
            asset_name_hint="ride.mp4",
            start_offset_s=0.0,
            end_offset_s=30.0,
            requested_duration_s=30.0,
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source=None,
        )


def test_direct_construction_rejected_with_whitespace_source_raises() -> None:
    with pytest.raises(ValueError, match="non-empty, non-whitespace"):
        CandidateClip(
            chapter_id="chapter_01",
            event_id="evt_001",
            asset_name_hint="ride.mp4",
            start_offset_s=0.0,
            end_offset_s=30.0,
            requested_duration_s=30.0,
            evidence_status=CandidateEvidenceStatus.REJECTED,
            evidence_source="   ",
        )


def test_direct_construction_awaiting_with_source_raises() -> None:
    with pytest.raises(ValueError, match="must be None"):
        CandidateClip(
            chapter_id="chapter_01",
            event_id="evt_001",
            asset_name_hint="ride.mp4",
            start_offset_s=0.0,
            end_offset_s=30.0,
            requested_duration_s=30.0,
            evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
            evidence_source="human_review",
        )
