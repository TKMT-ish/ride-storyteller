import json

import pytest

from app.demo import build_demo_candidate_edit_plan, build_demo_story_inputs, build_demo_story_plan
from app.edit import (
    CandidateClip,
    CandidateEditPlan,
    CandidateEvidenceStatus,
    build_candidate_edit_plan,
    confirm_clip_evidence,
    confirmed_event_ids,
    review_candidate_edit_plan,
)
from app.edit.candidate_planner import CandidatePlanStatus


def _clip(
    *,
    event_id: str = "evt_1",
    chapter_id: str = "chapter_1",
    evidence_status: CandidateEvidenceStatus = CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
    evidence_source: str | None = None,
    requested_duration_s: float = 100.0,
) -> CandidateClip:
    return CandidateClip(
        chapter_id=chapter_id,
        event_id=event_id,
        asset_name_hint="asset_hint",
        start_offset_s=0.0,
        end_offset_s=requested_duration_s,
        requested_duration_s=requested_duration_s,
        evidence_status=evidence_status,
        evidence_source=evidence_source,
    )


def _plan(
    clips: tuple[CandidateClip, ...], *, target_duration_s: float = 480.0
) -> CandidateEditPlan:
    candidate_duration_s = sum(clip.requested_duration_s for clip in clips)
    return CandidateEditPlan(
        story_title="title",
        target_duration_s=target_duration_s,
        candidate_duration_s=candidate_duration_s,
        coverage_ratio=candidate_duration_s / target_duration_s,
        status=CandidatePlanStatus.NEEDS_MORE_EVIDENCE,
        clips=clips,
    )


def test_candidate_plan_preserves_video_requests_without_visual_claims() -> None:
    plan, review = build_demo_candidate_edit_plan()

    assert plan.candidate_duration_s == pytest.approx(90)
    assert plan.coverage_ratio == pytest.approx(90 / 480)
    assert plan.status.value == "needs_more_evidence"
    assert all(clip.evidence_status.value == "awaiting_video_evidence" for clip in plan.clips)
    assert not review.is_ready_for_edit
    assert review.missing_duration_s == pytest.approx(390)
    assert "映像証拠が未確認" in " ".join(review.reasons)


def test_candidate_plan_rejects_story_events_missing_from_input() -> None:
    _, events = build_demo_story_inputs()
    story_plan = build_demo_story_plan()

    with pytest.raises(ValueError, match="story plan event is missing"):
        build_candidate_edit_plan(story_plan, events[:1])


# -- CandidateClip.__post_init__ boundary checks -----------------------------


def test_awaiting_clip_rejects_a_present_evidence_source() -> None:
    with pytest.raises(ValueError, match="must be None when status is awaiting_video_evidence"):
        _clip(
            evidence_status=CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE,
            evidence_source="human_review",
        )


@pytest.mark.parametrize(
    "status", [CandidateEvidenceStatus.CONFIRMED, CandidateEvidenceStatus.REJECTED]
)
def test_decided_clip_requires_a_non_empty_evidence_source(
    status: CandidateEvidenceStatus,
) -> None:
    with pytest.raises(ValueError, match="non-empty, non-whitespace string"):
        _clip(evidence_status=status, evidence_source=None)


@pytest.mark.parametrize("blank_source", ["", "   ", "\t\n"])
@pytest.mark.parametrize(
    "status", [CandidateEvidenceStatus.CONFIRMED, CandidateEvidenceStatus.REJECTED]
)
def test_decided_clip_rejects_blank_evidence_source(
    status: CandidateEvidenceStatus, blank_source: str
) -> None:
    with pytest.raises(ValueError, match="non-empty, non-whitespace string"):
        _clip(evidence_status=status, evidence_source=blank_source)


def test_decided_clip_accepts_a_non_empty_evidence_source() -> None:
    clip = _clip(
        evidence_status=CandidateEvidenceStatus.CONFIRMED, evidence_source="video_analysis"
    )
    assert clip.evidence_source == "video_analysis"


# -- confirm_clip_evidence ----------------------------------------------------


def test_confirm_clip_evidence_transitions_to_confirmed() -> None:
    clip = _clip()
    confirmed = confirm_clip_evidence(clip, confirmed=True, source="human_review")

    assert confirmed.evidence_status is CandidateEvidenceStatus.CONFIRMED
    assert confirmed.evidence_source == "human_review"
    # every other field is carried over unchanged
    assert confirmed.chapter_id == clip.chapter_id
    assert confirmed.event_id == clip.event_id
    assert confirmed.asset_name_hint == clip.asset_name_hint
    assert confirmed.start_offset_s == clip.start_offset_s
    assert confirmed.end_offset_s == clip.end_offset_s
    assert confirmed.requested_duration_s == clip.requested_duration_s


def test_confirm_clip_evidence_transitions_to_rejected() -> None:
    clip = _clip()
    rejected = confirm_clip_evidence(clip, confirmed=False, source="video_analysis")

    assert rejected.evidence_status is CandidateEvidenceStatus.REJECTED
    assert rejected.evidence_source == "video_analysis"


@pytest.mark.parametrize("blank_source", ["", "   "])
def test_confirm_clip_evidence_rejects_blank_source(blank_source: str) -> None:
    with pytest.raises(ValueError, match="source must be a non-empty"):
        confirm_clip_evidence(_clip(), confirmed=True, source=blank_source)


@pytest.mark.parametrize(
    "status", [CandidateEvidenceStatus.CONFIRMED, CandidateEvidenceStatus.REJECTED]
)
def test_confirm_clip_evidence_blocks_redeciding_an_already_decided_clip(
    status: CandidateEvidenceStatus,
) -> None:
    decided = _clip(evidence_status=status, evidence_source="human_review")

    with pytest.raises(ValueError, match="only awaiting clips may be updated"):
        confirm_clip_evidence(decided, confirmed=True, source="video_analysis")


# -- review_candidate_edit_plan -----------------------------------------------


def test_review_reports_ready_when_confirmed_duration_meets_target() -> None:
    clips = (
        _clip(
            event_id="evt_1",
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="s",
            requested_duration_s=300,
        ),
        _clip(
            event_id="evt_2",
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="s",
            requested_duration_s=200,
        ),
    )
    review = review_candidate_edit_plan(_plan(clips, target_duration_s=480))

    assert review.is_ready_for_edit
    assert review.missing_duration_s == 0
    assert review.reasons == ()
    assert review.event_ids_requiring_evidence == ()
    assert review.rejected_event_ids == ()


def test_review_reports_missing_duration_when_short() -> None:
    clips = (
        _clip(
            event_id="evt_1",
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="s",
            requested_duration_s=100,
        ),
    )
    review = review_candidate_edit_plan(_plan(clips, target_duration_s=480))

    assert not review.is_ready_for_edit
    assert review.missing_duration_s == pytest.approx(380)
    assert "目標尺" in " ".join(review.reasons)


def test_review_blocks_on_pending_evidence_even_if_duration_is_met() -> None:
    clips = (
        _clip(
            event_id="evt_1",
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="s",
            requested_duration_s=480,
        ),
        _clip(event_id="evt_2", requested_duration_s=0),
    )
    review = review_candidate_edit_plan(_plan(clips, target_duration_s=480))

    assert not review.is_ready_for_edit
    assert review.event_ids_requiring_evidence == ("evt_2",)
    assert "映像証拠が未確認" in " ".join(review.reasons)


def test_review_lists_rejected_clips_for_transparency_without_blocking_readiness() -> None:
    """Per the 2026-09-01 decision: a rejected clip is reported but does not
    by itself block readiness once duration and pending checks pass."""
    clips = (
        _clip(
            event_id="evt_1",
            evidence_status=CandidateEvidenceStatus.CONFIRMED,
            evidence_source="s",
            requested_duration_s=480,
        ),
        _clip(
            event_id="evt_2",
            evidence_status=CandidateEvidenceStatus.REJECTED,
            evidence_source="s",
            requested_duration_s=0,
        ),
    )
    review = review_candidate_edit_plan(_plan(clips, target_duration_s=480))

    assert review.is_ready_for_edit
    assert review.rejected_event_ids == ("evt_2",)
    assert "映像証拠が不適切" in " ".join(review.reasons)


def test_review_requires_at_least_one_confirmed_clip() -> None:
    """Duration met and nothing pending, but every clip was rejected: still
    not ready because there is nothing confirmed to build from."""
    clips = (
        _clip(
            event_id="evt_1",
            evidence_status=CandidateEvidenceStatus.REJECTED,
            evidence_source="s",
            requested_duration_s=480,
        ),
    )
    review = review_candidate_edit_plan(_plan(clips, target_duration_s=480))

    assert not review.is_ready_for_edit
    assert review.missing_duration_s == 0
    assert review.event_ids_requiring_evidence == ()


# -- confirmed_event_ids -------------------------------------------------------


def test_confirmed_event_ids_returns_only_confirmed_clips_in_order() -> None:
    clips = (
        _clip(
            event_id="evt_1", evidence_status=CandidateEvidenceStatus.CONFIRMED, evidence_source="s"
        ),
        _clip(
            event_id="evt_2", evidence_status=CandidateEvidenceStatus.REJECTED, evidence_source="s"
        ),
        _clip(event_id="evt_3"),
        _clip(
            event_id="evt_4", evidence_status=CandidateEvidenceStatus.CONFIRMED, evidence_source="s"
        ),
    )
    assert confirmed_event_ids(_plan(clips)) == ("evt_1", "evt_4")


def test_confirmed_event_ids_empty_when_none_confirmed() -> None:
    clips = (_clip(event_id="evt_1"),)
    assert confirmed_event_ids(_plan(clips)) == ()


# -- to_dict() serialization ----------------------------------------------------


def test_candidate_clip_to_dict_uses_plain_values_and_is_json_serializable() -> None:
    clip = _clip(evidence_status=CandidateEvidenceStatus.CONFIRMED, evidence_source="human_review")
    payload = clip.to_dict()

    assert payload["evidence_status"] == "confirmed"
    assert isinstance(payload["evidence_status"], str)
    json.dumps(payload)  # raises if anything is not JSON-serializable


def test_candidate_edit_plan_to_dict_nests_clip_dicts_and_is_json_serializable() -> None:
    plan, _ = build_demo_candidate_edit_plan()
    payload = plan.to_dict()

    assert payload["status"] == plan.status.value
    assert isinstance(payload["status"], str)
    assert payload["clips"] == [clip.to_dict() for clip in plan.clips]
    json.dumps(payload)


def test_candidate_edit_review_to_dict_uses_lists_not_tuples() -> None:
    _, review = build_demo_candidate_edit_plan()
    payload = review.to_dict()

    assert isinstance(payload["reasons"], list)
    assert isinstance(payload["event_ids_requiring_evidence"], list)
    assert isinstance(payload["rejected_event_ids"], list)
    json.dumps(payload)


# -- build_candidate_edit_plan --------------------------------------------------


def test_build_candidate_edit_plan_starts_every_clip_awaiting_evidence() -> None:
    plan, _ = build_demo_candidate_edit_plan()

    assert plan.status is CandidatePlanStatus.NEEDS_MORE_EVIDENCE
    for clip in plan.clips:
        assert clip.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE
        assert clip.evidence_source is None
