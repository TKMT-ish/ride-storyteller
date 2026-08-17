import pytest

from app.demo import build_demo_candidate_edit_plan, build_demo_story_inputs, build_demo_story_plan
from app.edit import build_candidate_edit_plan


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
