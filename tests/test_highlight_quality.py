import json
from dataclasses import replace

import pytest

from app.video.apple_vision import VisionClassification, VisionImageAnalysis
from app.video.gpmf_metrics import GpmfWindowSummary
from app.video.highlight_discovery import WindowFeatures
from app.video.highlight_quality import (
    HighlightWindowEvidence,
    InterestLane,
    QualitySelectionMethod,
    evaluate_interest_gate,
    evaluate_quality_selection,
    export_quality_research_manifest,
    passes_complete_evidence_gate,
    passes_strict_interest_gate,
    score_highlight_evidence,
    select_quality_highlights,
)


def _window(
    asset_id: str,
    *,
    timeline_s: float = 0,
    start_offset_s: float = 0,
    minimum_speed: float = 8,
    speed_p10: float = 9,
    center_speed: float = 10,
    moving_ratio: float = 1,
    heading: float = 25,
    center_heading: float | None = None,
    accumulated_heading: float = 30,
    path_efficiency: float = 0.96,
    motion: float = 12,
    motion_std: float = 2,
    scene: float = 10,
    scene_peaks: float = 0.2,
    blur: float = 4,
) -> WindowFeatures:
    return WindowFeatures(
        asset_id=asset_id,
        start_offset_s=start_offset_s,
        duration_s=12,
        timeline_s=timeline_s,
        mean_speed_mps=12,
        minimum_speed_mps=minimum_speed,
        speed_p10_mps=speed_p10,
        center_speed_mps=center_speed,
        moving_ratio=moving_ratio,
        heading_change_degrees=heading,
        center_heading_change_degrees=heading if center_heading is None else center_heading,
        accumulated_heading_change_degrees=accumulated_heading,
        path_efficiency=path_efficiency,
        speed_std_mps=2,
        speed_range_mps=5,
        elevation_change_m=2,
        elevation_range_m=5,
        motion_mean=motion,
        motion_std=motion_std,
        scene_change_mean=scene,
        scene_change_peak_ratio=scene_peaks,
        blur_mean=blur,
        luma_mean=128,
        dynamic_range_mean=170,
        saturation_mean=25,
        entropy_mean=0.9,
    )


def _gpmf(
    *,
    coverage: float = 1,
    natural: float = 0.7,
    gyro: float = 0.3,
    center_gyro: float = 0.3,
) -> GpmfWindowSummary:
    return GpmfWindowSummary(
        gyro_sustained_rad_s=gyro,
        center_gyro_sustained_rad_s=center_gyro,
        gyro_jitter_rad_s=0.1,
        gyro_peak_rad_s=0.8,
        acceleration_jitter_mps2=0.4,
        iso_mean=100,
        shutter_mean_s=0.001,
        luma_mean=128,
        uniformity_mean=0.2,
        natural_scene_probability=natural,
        built_scene_probability=1 - natural,
        scene_confidence=0.7,
        hue_weight_mean=0.5,
        coverage_ratio=coverage,
    )


def _evidence(
    index: int,
    *,
    timeline_s: float | None = None,
    aesthetic: float = 0.5,
    utility: bool = False,
    road: bool = True,
    **window_values: float,
) -> HighlightWindowEvidence:
    frame_indices = (index * 3, index * 3 + 1, index * 3 + 2)
    frames = tuple(
        VisionImageAnalysis(
            index=frame_index,
            aesthetic_score=aesthetic,
            is_utility=utility,
            classifications=(
                VisionClassification("outdoor sky", 0.8),
                *(
                    (VisionClassification("road", 0.7),)
                    if road
                    else (VisionClassification("automobile", 0.8),)
                ),
            ),
        )
        for frame_index in frame_indices
    )
    return HighlightWindowEvidence(
        window=_window(
            f"asset-{index}",
            timeline_s=index * 100 if timeline_s is None else timeline_s,
            start_offset_s=index * 20,
            **window_values,
        ),
        gpmf=_gpmf(),
        frames=frames,
        feature_index=frame_indices[1],
    )


def _distance(first: int, second: int) -> float:
    return abs(first - second) / 10


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"minimum_speed": 0.0}, False),
        ({"speed_p10": 1.0}, False),
        ({"center_speed": 1.0}, False),
        ({"moving_ratio": 0.5}, False),
        ({"motion": 1.0}, False),
        (
            {
                "heading": 1.0,
                "accumulated_heading": 2.0,
                "path_efficiency": 1.0,
            },
            False,
        ),
    ],
)
def test_strict_gate_rejects_stops_and_straight_dull_windows(
    overrides: dict[str, float], expected: bool
) -> None:
    assert passes_strict_interest_gate(_window("asset", **overrides)) is expected


def test_interest_gate_separates_strong_turn_from_temporal_visual_event() -> None:
    strong_turn = evaluate_interest_gate(_window("strong-turn"))
    assert strong_turn.passes is True
    assert strong_turn.lanes == (InterestLane.STRONG_TURN,)

    visual_event = evaluate_interest_gate(
        _window(
            "visual-event",
            heading=1,
            center_heading=1,
            accumulated_heading=2,
            path_efficiency=1,
            scene=12,
            scene_peaks=0.2,
            motion_std=1.5,
        )
    )
    assert visual_event.passes is True
    assert visual_event.lanes == (InterestLane.VISUAL_EVENT,)

    weak_road = evaluate_interest_gate(
        _window(
            "weak-road",
            heading=1,
            center_heading=1,
            accumulated_heading=2,
            path_efficiency=1,
            scene=5,
            scene_peaks=0.1,
            motion_std=0.5,
        )
    )
    assert weak_road.passes is False
    assert weak_road.lanes == ()


def test_evidence_fails_closed_on_incomplete_frames_or_telemetry() -> None:
    frame = VisionImageAnalysis(0, 0.5, False, ())

    with pytest.raises(ValueError, match="three Vision frames"):
        HighlightWindowEvidence(_window("asset"), _gpmf(), (frame,), 0)
    with pytest.raises(ValueError, match="GPMF coverage"):
        HighlightWindowEvidence(
            _window("asset"),
            _gpmf(coverage=0.2),
            (frame, VisionImageAnalysis(1, 0.5, False, ()), VisionImageAnalysis(2, 0.5, False, ())),
            1,
        )


def test_complete_evidence_gate_rejects_nonroad_parking_context() -> None:
    assert passes_complete_evidence_gate(_evidence(1)) is True
    assert (
        passes_complete_evidence_gate(
            _evidence(
                7,
                heading=1,
                center_heading=1,
                accumulated_heading=2,
                path_efficiency=1,
                scene=12,
                scene_peaks=0.2,
                motion_std=1.5,
            )
        )
        is True
    )
    assert passes_complete_evidence_gate(_evidence(2, road=False)) is False
    assert passes_complete_evidence_gate(_evidence(3, utility=True)) is False
    low_gyro = _evidence(4)
    low_gyro = HighlightWindowEvidence(
        low_gyro.window,
        _gpmf(gyro=0.01),
        low_gyro.frames,
        low_gyro.feature_index,
    )
    assert passes_complete_evidence_gate(low_gyro) is False
    low_center_gyro = _evidence(5)
    low_center_gyro = HighlightWindowEvidence(
        low_center_gyro.window,
        _gpmf(center_gyro=0.01),
        low_center_gyro.frames,
        low_center_gyro.feature_index,
    )
    assert passes_complete_evidence_gate(low_center_gyro) is False
    low_center_heading = _evidence(6, heading=20)
    low_center_heading = HighlightWindowEvidence(
        replace(low_center_heading.window, center_heading_change_degrees=2.0),
        low_center_heading.gpmf,
        low_center_heading.frames,
        low_center_heading.feature_index,
    )
    assert passes_complete_evidence_gate(low_center_heading) is False


def test_quality_score_rewards_aesthetic_sharp_frame_set() -> None:
    good = _evidence(1, aesthetic=0.8, blur=2)
    weak = _evidence(2, aesthetic=-0.3, blur=12)

    scored = score_highlight_evidence((good, weak))

    by_asset = {item.evidence.window.asset_id: item for item in scored}
    assert by_asset["asset-1"].quality_score > by_asset["asset-2"].quality_score


def test_selector_rejects_feature_duplicates_and_keeps_windows_unique() -> None:
    scored = score_highlight_evidence(tuple(_evidence(index) for index in range(5)))

    def duplicate_distance(first: int, second: int) -> float:
        if {first, second} == {1, 4}:
            return 0.0
        return _distance(first, second)

    selected = select_quality_highlights(
        scored,
        method=QualitySelectionMethod.BALANCED_DIVERSE,
        distance=duplicate_distance,
        top_k=5,
        minimum_separation_s=0,
    )

    keys = {(item.asset_id, item.start_offset_s) for item in selected}
    assert len(keys) == len(selected)
    assert not ({"asset-0", "asset-1"} <= {item.asset_id for item in selected})


def test_selector_enforces_temporal_separation() -> None:
    scored = score_highlight_evidence(
        (_evidence(0, timeline_s=0), _evidence(1, timeline_s=10), _evidence(2, timeline_s=80))
    )

    selected = select_quality_highlights(
        scored,
        method=QualitySelectionMethod.QUALITY_FIRST,
        distance=_distance,
        top_k=3,
        minimum_separation_s=30,
    )

    times = [item.scored.evidence.window.timeline_s for item in selected]
    assert all(
        abs(first - second) >= 30
        for index, first in enumerate(times)
        for second in times[index + 1 :]
    )


def test_balanced_selector_covers_route_buckets_and_evaluation_is_complete() -> None:
    scored = score_highlight_evidence(tuple(_evidence(index) for index in range(10)))
    selected = select_quality_highlights(
        scored,
        method=QualitySelectionMethod.BALANCED_DIVERSE,
        distance=_distance,
        top_k=5,
        minimum_separation_s=0,
    )

    evaluation = evaluate_quality_selection(
        selected,
        population=scored,
        distance=_distance,
    )

    assert evaluation.selected_count == 5
    assert evaluation.unique_window_count == 5
    assert evaluation.route_bucket_coverage == 5
    assert evaluation.hard_gate_violation_count == 0
    assert evaluation.minimum_pairwise_distance > 0


def test_manifest_excludes_paths_coordinates_timestamps_and_vision_labels() -> None:
    scored = score_highlight_evidence(tuple(_evidence(index) for index in range(3)))
    selection = select_quality_highlights(
        scored,
        method=QualitySelectionMethod.QUALITY_FIRST,
        distance=_distance,
        top_k=2,
        minimum_separation_s=0,
    )
    evaluation = evaluate_quality_selection(
        selection,
        population=scored,
        distance=_distance,
    )

    manifest = export_quality_research_manifest(
        {QualitySelectionMethod.QUALITY_FIRST: selection},
        {QualitySelectionMethod.QUALITY_FIRST: evaluation},
        analyzed_window_count=10,
        strict_gate_count=3,
        complete_evidence_count=3,
        evidence_gate_count=3,
    )
    payload = json.loads(manifest)

    assert "/Users/" not in manifest
    assert "latitude" not in manifest
    assert "longitude" not in manifest
    assert "timeline_s" not in manifest
    assert "outdoor sky" not in manifest
    assert payload["privacy"]["external_data_sent"] is False
    assert payload["schema_version"] == "local-highlight-research-v2"
    assert payload["methods"]["01-quality-first"]["candidates"][0]["interest_lanes"] == [
        "strong_turn"
    ]
