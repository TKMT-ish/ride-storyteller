from dataclasses import replace
from pathlib import Path

import pytest

import app.video.highlight_review as highlight_review_module
from app.video.apple_vision import VisionClassification, VisionImageAnalysis
from app.video.gpmf_metrics import GpmfWindowSummary
from app.video.highlight_discovery import WindowFeatures
from app.video.highlight_quality import (
    HighlightWindowEvidence,
    InterestLane,
    QualitySelection,
    QualitySelectionMethod,
    ScoredHighlightWindow,
)
from app.video.highlight_review import (
    HighlightReview,
    HighlightReviewDecision,
    HighlightReviewReason,
    HighlightReviewStatus,
    build_highlight_review_template,
    evaluate_highlight_review,
    highlight_review_candidate_id,
    load_highlight_review,
    load_or_create_highlight_review,
    update_highlight_review_decision,
    write_highlight_review,
)


def _selection(
    method: QualitySelectionMethod,
    rank: int,
    *,
    asset_id: str,
) -> QualitySelection:
    window = WindowFeatures(
        asset_id=asset_id,
        start_offset_s=rank * 12.0,
        duration_s=12.0,
        timeline_s=rank * 100.0,
        mean_speed_mps=12.0,
        minimum_speed_mps=8.0,
        speed_p10_mps=9.0,
        center_speed_mps=10.0,
        moving_ratio=1.0,
        heading_change_degrees=24.0,
        center_heading_change_degrees=14.0,
        accumulated_heading_change_degrees=34.0,
        path_efficiency=0.95,
        speed_std_mps=2.0,
        speed_range_mps=4.0,
        elevation_change_m=2.0,
        elevation_range_m=4.0,
        motion_mean=10.0,
        motion_std=2.0,
        scene_change_mean=12.0,
        scene_change_peak_ratio=0.2,
        blur_mean=3.0,
        luma_mean=120.0,
        dynamic_range_mean=180.0,
        saturation_mean=25.0,
        entropy_mean=0.9,
    )
    frames = tuple(
        VisionImageAnalysis(
            index=rank * 10 + index,
            aesthetic_score=0.5,
            is_utility=False,
            classifications=(VisionClassification("road", 0.9),),
        )
        for index in range(3)
    )
    evidence = HighlightWindowEvidence(
        window=window,
        gpmf=GpmfWindowSummary(
            gyro_sustained_rad_s=0.2,
            center_gyro_sustained_rad_s=0.2,
            gyro_jitter_rad_s=0.1,
            gyro_peak_rad_s=0.4,
            acceleration_jitter_mps2=1.0,
            iso_mean=100.0,
            shutter_mean_s=0.001,
            luma_mean=120.0,
            uniformity_mean=0.2,
            natural_scene_probability=0.7,
            built_scene_probability=0.3,
            scene_confidence=0.6,
            hue_weight_mean=0.5,
            coverage_ratio=1.0,
        ),
        frames=frames,
        feature_index=frames[1].index,
    )
    return QualitySelection(
        method=method,
        rank=rank,
        scored=ScoredHighlightWindow(
            evidence=evidence,
            interest_lanes=(InterestLane.STRONG_TURN,),
            quality_score=0.8,
            dynamics_score=0.8,
            scenic_score=0.8,
            balanced_score=0.8,
        ),
        relevance_score=0.8,
        diversity_gain=0.5,
    )


def _selections() -> dict[QualitySelectionMethod, tuple[QualitySelection, ...]]:
    return {
        QualitySelectionMethod.QUALITY_FIRST: (
            _selection(QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="asset-a"),
        ),
        QualitySelectionMethod.RIDE_DYNAMICS: (
            _selection(QualitySelectionMethod.RIDE_DYNAMICS, 1, asset_id="asset-b"),
        ),
    }


def test_highlight_review_template_uses_opaque_current_candidate_ids() -> None:
    selections = _selections()

    review = build_highlight_review_template(selections)

    assert len(review.decisions) == 2
    assert all(decision.status is HighlightReviewStatus.AWAITING for decision in review.decisions)
    assert all(not decision.reasons for decision in review.decisions)
    assert review.decisions[0].candidate_id == highlight_review_candidate_id(
        selections[QualitySelectionMethod.QUALITY_FIRST][0]
    )


def test_highlight_review_decision_reasons_match_status() -> None:
    with pytest.raises(ValueError, match="awaiting highlight review"):
        HighlightReviewDecision(
            "candidate", QualitySelectionMethod.QUALITY_FIRST, 1, HighlightReviewStatus.AWAITING,
            (HighlightReviewReason.CLEAR_TURN,),
        )
    with pytest.raises(ValueError, match="do not match"):
        HighlightReviewDecision(
            "candidate", QualitySelectionMethod.QUALITY_FIRST, 1, HighlightReviewStatus.APPROVED,
            (HighlightReviewReason.TOO_STRAIGHT,),
        )
    with pytest.raises(ValueError, match="do not match"):
        HighlightReviewDecision(
            "candidate", QualitySelectionMethod.QUALITY_FIRST, 1, HighlightReviewStatus.REJECTED,
            (),
        )


def test_highlight_review_evaluation_reports_approval_rejection_and_reason_counts() -> None:
    template = build_highlight_review_template(_selections())
    review = HighlightReview(
        (
            replace(
                template.decisions[0],
                status=HighlightReviewStatus.APPROVED,
                reasons=(HighlightReviewReason.CLEAR_TURN,),
            ),
            replace(
                template.decisions[1],
                status=HighlightReviewStatus.REJECTED,
                reasons=(HighlightReviewReason.TOO_STRAIGHT,),
            ),
        )
    )

    result = evaluate_highlight_review(_selections(), review)

    assert result.is_complete is True
    assert result.approved_candidate_ids == (template.decisions[0].candidate_id,)
    assert result.rejected_candidate_ids == (template.decisions[1].candidate_id,)
    assert result.reason_counts == {
        HighlightReviewReason.CLEAR_TURN: 1,
        HighlightReviewReason.TOO_STRAIGHT: 1,
    }


def test_highlight_review_rejects_stale_candidates() -> None:
    review = build_highlight_review_template(_selections())
    changed = _selections()
    changed[QualitySelectionMethod.QUALITY_FIRST] = (
        _selection(QualitySelectionMethod.QUALITY_FIRST, 1, asset_id="different-asset"),
    )

    with pytest.raises(ValueError, match="exactly the current review candidates"):
        evaluate_highlight_review(changed, review)


def test_highlight_review_round_trip_preserves_current_review(tmp_path: Path) -> None:
    path = tmp_path / "highlight-review.json"
    selections = _selections()

    created = load_or_create_highlight_review(path, selections)
    assert load_highlight_review(path) == created
    assert load_or_create_highlight_review(path, selections) == created
    with pytest.raises(FileExistsError, match="already exists"):
        write_highlight_review(path, created)
    assert write_highlight_review(path, created, overwrite=True) == path


def test_highlight_review_atomic_write_preserves_existing_review_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "highlight-review.json"
    original = build_highlight_review_template(_selections())
    write_highlight_review(path, original)
    original_payload = path.read_text(encoding="utf-8")
    updated = update_highlight_review_decision(
        original,
        candidate_id=original.decisions[0].candidate_id,
        status=HighlightReviewStatus.APPROVED,
        reasons=(HighlightReviewReason.CLEAR_TURN,),
    )

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(highlight_review_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_highlight_review(path, updated, overwrite=True)

    assert path.read_text(encoding="utf-8") == original_payload
    assert not list(tmp_path.glob(".highlight-review.json.*.tmp"))


def test_highlight_review_payload_excludes_private_selection_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "highlight-review.json"
    review = build_highlight_review_template(_selections())
    write_highlight_review(path, review)

    payload = path.read_text(encoding="utf-8")
    assert "asset-a" not in payload
    assert "asset-b" not in payload
    assert "start_offset" not in payload
    assert "file_name" not in payload
    assert "path" not in payload


def test_update_highlight_review_decision_keeps_candidate_identity_and_order() -> None:
    template = build_highlight_review_template(_selections())
    target = template.decisions[0]

    updated = update_highlight_review_decision(
        template,
        candidate_id=target.candidate_id,
        status=HighlightReviewStatus.APPROVED,
        reasons=(HighlightReviewReason.CLEAR_TURN,),
    )

    assert [item.candidate_id for item in updated.decisions] == [
        item.candidate_id for item in template.decisions
    ]
    assert updated.decisions[0].status is HighlightReviewStatus.APPROVED
    assert updated.decisions[0].reasons == (HighlightReviewReason.CLEAR_TURN,)


def test_update_highlight_review_decision_rejects_unknown_candidate() -> None:
    with pytest.raises(ValueError, match="unknown"):
        update_highlight_review_decision(
            build_highlight_review_template(_selections()),
            candidate_id="highlight-unknown",
            status=HighlightReviewStatus.AWAITING,
        )
