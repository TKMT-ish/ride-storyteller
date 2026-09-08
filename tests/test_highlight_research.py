import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from app.video.apple_vision import VisionImageAnalysis
from app.video.gpmf_metrics import GpmfMetricSample, GpmfWindowSummary
from app.video.highlight_discovery import HighlightWindowAnalysis, WindowFeatures
from app.video.highlight_quality import (
    HighlightWindowEvidence,
    QualitySelection,
    QualitySelectionEvaluation,
    QualitySelectionMethod,
    ScoredHighlightWindow,
)
from app.video.highlight_research import (
    HighlightResearchError,
    _build_complete_evidence,
    _build_contact_sheet,
    _build_diversity_pool,
    _extract_research_clips,
    _remap_vision_distance,
    _validate_private_output_directory,
    _write_private_research_state,
    build_contact_sheet_command,
    build_frame_extraction_command,
    run_local_highlight_research,
)
from app.video.metric_cache import PrivateMetricCache


def _window(asset_id: str, *, timeline_s: float, start_offset_s: float) -> WindowFeatures:
    return WindowFeatures(
        asset_id=asset_id,
        start_offset_s=start_offset_s,
        duration_s=12,
        timeline_s=timeline_s,
        mean_speed_mps=12,
        minimum_speed_mps=8,
        speed_p10_mps=9,
        center_speed_mps=10,
        moving_ratio=1,
        heading_change_degrees=25,
        center_heading_change_degrees=25,
        accumulated_heading_change_degrees=30,
        path_efficiency=0.96,
        speed_std_mps=2,
        speed_range_mps=5,
        elevation_change_m=2,
        elevation_range_m=5,
        motion_mean=12,
        motion_std=2,
        scene_change_mean=10,
        scene_change_peak_ratio=0.2,
        blur_mean=4,
        luma_mean=128,
        dynamic_range_mean=170,
        saturation_mean=25,
        entropy_mean=0.9,
    )


def _gpmf() -> GpmfWindowSummary:
    return GpmfWindowSummary(
        gyro_sustained_rad_s=0.3,
        center_gyro_sustained_rad_s=0.3,
        gyro_jitter_rad_s=0.1,
        gyro_peak_rad_s=0.8,
        acceleration_jitter_mps2=0.4,
        iso_mean=100,
        shutter_mean_s=0.001,
        luma_mean=128,
        uniformity_mean=0.2,
        natural_scene_probability=0.7,
        built_scene_probability=0.3,
        scene_confidence=0.7,
        hue_weight_mean=0.5,
        coverage_ratio=1,
    )


def _evidence(index: int) -> HighlightWindowEvidence:
    frame_indices = (index * 3, index * 3 + 1, index * 3 + 2)
    frames = tuple(
        VisionImageAnalysis(
            index=frame_index, aesthetic_score=0.5, is_utility=False, classifications=()
        )
        for frame_index in frame_indices
    )
    return HighlightWindowEvidence(
        window=_window(f"asset-{index}", timeline_s=index * 100, start_offset_s=index * 20),
        gpmf=_gpmf(),
        frames=frames,
        feature_index=frame_indices[1],
    )


def _scored(
    index: int,
    *,
    quality: float = 0.0,
    dynamics: float = 0.0,
    scenic: float = 0.0,
    balanced: float = 0.0,
) -> ScoredHighlightWindow:
    return ScoredHighlightWindow(
        evidence=_evidence(index),
        interest_lanes=(),
        quality_score=quality,
        dynamics_score=dynamics,
        scenic_score=scenic,
        balanced_score=balanced,
    )


def _completed(returncode: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout="", stderr="")


def _gpmf_sample(*, time_s: float = 0.0, duration_s: float = 12.0) -> GpmfMetricSample:
    return GpmfMetricSample(
        time_s=time_s,
        duration_s=duration_s,
        gyro_sustained_rad_s=0.3,
        gyro_jitter_rad_s=0.1,
        gyro_peak_rad_s=0.8,
        acceleration_jitter_mps2=0.4,
        iso_mean=100,
        shutter_mean_s=0.001,
        luma_mean=128,
        uniformity_mean=0.2,
        natural_scene_probability=0.7,
        built_scene_probability=0.3,
        scene_confidence=0.7,
        hue_weight_mean=0.5,
    )


def _seed_gpmf_cache(
    cache: PrivateMetricCache, source_path: Path, samples: tuple[GpmfMetricSample, ...]
) -> None:
    """Populate the cache so `_build_complete_evidence` never calls the real analyzer."""
    cache.load_or_analyze_gpmf_metrics(source_path, lambda _path: samples)


def _write_file(path: Path, content: bytes = b"local-only-fixture-bytes") -> Path:
    path.write_bytes(content)
    return path


def _evidence_command_runner(
    probe_path: Path, *, frame_extraction_ok: bool = True, probe_compiles: bool = True
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Answer `_build_complete_evidence`'s three kinds of subprocess call.

    Distinguished by `command[0]`: `ffmpeg` extracts a frame, `xcrun` compiles
    the Apple Vision probe, and the probe's own path runs the (fake) analysis.
    No real ffmpeg, compiler, or Vision framework is touched.
    """

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        program = command[0]
        if program == "ffmpeg":
            if frame_extraction_ok:
                Path(command[-1]).write_bytes(b"jpg")
            return _completed(0 if frame_extraction_ok else 1)
        if program == "xcrun":
            if probe_compiles:
                probe_path.write_text("#!/bin/sh\n")
            return _completed(0 if probe_compiles else 1)
        if program == str(probe_path):
            images = [arg for arg in command[1:] if arg != "--no-distances"]
            items = [
                {"index": index, "aestheticScore": 0.5, "isUtility": False, "classifications": []}
                for index in range(len(images))
            ]
            payload = {"schemaVersion": "ride-apple-vision-v1", "items": items, "distances": []}
            return subprocess.CompletedProcess(
                args=(), returncode=0, stdout=json.dumps(payload), stderr=""
            )
        raise AssertionError(f"unexpected command: {command}")

    return runner


def _quality_selection(method: QualitySelectionMethod, rank: int, index: int) -> QualitySelection:
    return QualitySelection(
        method=method,
        rank=rank,
        scored=_scored(index),
        relevance_score=0.5,
        diversity_gain=0.1,
    )


def _all_method_selections(
    overrides: dict[QualitySelectionMethod, tuple[QualitySelection, ...]],
) -> dict[QualitySelectionMethod, tuple[QualitySelection, ...]]:
    """Every `QualitySelectionMethod` needs a key; `_extract_research_clips` indexes without
    `.get`."""
    return {method: overrides.get(method, ()) for method in QualitySelectionMethod}


def _clip_command_runner(*, ok: bool = True) -> Callable[..., subprocess.CompletedProcess[str]]:
    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[0] == "ffmpeg"
        if ok:
            Path(command[-1]).write_bytes(b"clip")
        return _completed(0 if ok else 1)

    return runner


def test_frame_extraction_command_uses_one_local_proxy_and_three_quarter_safe_output(
    tmp_path: Path,
) -> None:
    proxy = tmp_path / "proxy file.lrv"
    output = tmp_path / "frame.jpg"

    command = build_frame_extraction_command(
        proxy,
        output,
        time_s=12.5,
        overwrite=False,
    )

    assert command[command.index("-i") + 1] == str(proxy)
    assert command[command.index("-ss") + 1] == "12.5"
    assert "scale=640:-2" in command
    assert command[-1] == str(output)


def test_frame_extraction_rejects_negative_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        build_frame_extraction_command(
            tmp_path / "proxy.lrv",
            tmp_path / "frame.jpg",
            time_s=-1,
            overwrite=False,
        )


def test_frame_extraction_command_allows_exactly_zero_time(tmp_path: Path) -> None:
    command = build_frame_extraction_command(
        tmp_path / "proxy.lrv",
        tmp_path / "frame.jpg",
        time_s=0.0,
        overwrite=False,
    )

    assert command[command.index("-ss") + 1] == "0.0"


def test_frame_extraction_command_rounds_timestamp_to_six_decimals(tmp_path: Path) -> None:
    command = build_frame_extraction_command(
        tmp_path / "proxy.lrv",
        tmp_path / "frame.jpg",
        time_s=1.23456789,
        overwrite=False,
    )

    assert command[command.index("-ss") + 1] == "1.234568"


def test_frame_extraction_command_overwrite_flag_picks_dash_y_or_dash_n(
    tmp_path: Path,
) -> None:
    overwrite_command = build_frame_extraction_command(
        tmp_path / "proxy.lrv", tmp_path / "frame.jpg", time_s=1.0, overwrite=True
    )
    keep_command = build_frame_extraction_command(
        tmp_path / "proxy.lrv", tmp_path / "frame.jpg", time_s=1.0, overwrite=False
    )

    assert "-y" in overwrite_command and "-n" not in overwrite_command
    assert "-n" in keep_command and "-y" not in keep_command


def test_contact_sheet_command_calculates_grid_without_shell_glob(tmp_path: Path) -> None:
    command = build_contact_sheet_command(
        tmp_path / "thumbnails",
        tmp_path / "sheet.jpg",
        thumbnail_count=12,
        overwrite=True,
    )

    assert command[command.index("-pattern_type") + 1] == "glob"
    assert command[command.index("-i") + 1].endswith("*.jpg")
    assert "tile=5x3" in command[command.index("-vf") + 1]


def test_contact_sheet_command_rejects_zero_and_negative_thumbnail_count(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="at least one thumbnail"):
        build_contact_sheet_command(
            tmp_path, tmp_path / "sheet.jpg", thumbnail_count=0, overwrite=True
        )
    with pytest.raises(ValueError, match="at least one thumbnail"):
        build_contact_sheet_command(
            tmp_path, tmp_path / "sheet.jpg", thumbnail_count=-1, overwrite=True
        )


def test_contact_sheet_command_grid_boundaries(tmp_path: Path) -> None:
    single = build_contact_sheet_command(
        tmp_path, tmp_path / "sheet.jpg", thumbnail_count=1, overwrite=True
    )
    assert "tile=1x1" in single[single.index("-vf") + 1]

    exact_row = build_contact_sheet_command(
        tmp_path, tmp_path / "sheet.jpg", thumbnail_count=5, overwrite=True
    )
    assert "tile=5x1" in exact_row[exact_row.index("-vf") + 1]

    next_row = build_contact_sheet_command(
        tmp_path, tmp_path / "sheet.jpg", thumbnail_count=6, overwrite=True
    )
    assert "tile=5x2" in next_row[next_row.index("-vf") + 1]


def test_contact_sheet_command_overwrite_flag_picks_dash_y_or_dash_n(
    tmp_path: Path,
) -> None:
    overwrite_command = build_contact_sheet_command(
        tmp_path, tmp_path / "sheet.jpg", thumbnail_count=3, overwrite=True
    )
    keep_command = build_contact_sheet_command(
        tmp_path, tmp_path / "sheet.jpg", thumbnail_count=3, overwrite=False
    )

    assert "-y" in overwrite_command and "-n" not in overwrite_command
    assert "-n" in keep_command and "-y" not in keep_command


def test_research_rejects_public_repository_output() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private directory"):
        run_local_highlight_research(
            Path("missing.gpx"),
            Path("missing-video"),
            Path("missing-catalog.json"),
            repository_root / "unsafe-research-output",
        )


def test_remapped_vision_distance_rejects_candidates_outside_bounded_pool() -> None:
    def distance(first: int, second: int) -> float:
        return abs(first - second) / 10

    remapped = _remap_vision_distance((10, 20, 30), distance)

    assert remapped(10, 30) == pytest.approx(0.2)
    with pytest.raises(KeyError, match="outside the diversity pool"):
        remapped(10, 40)


def test_remap_vision_distance_rejects_duplicate_feature_indices() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        _remap_vision_distance((10, 10, 20), lambda first, second: 0.0)


def test_diversity_pool_requires_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _build_diversity_pool((), per_method=0)


def test_diversity_pool_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _build_diversity_pool((), per_method=-1)


def test_validate_private_output_directory_rejects_path_outside_repository(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must stay inside the repository"):
        _validate_private_output_directory(tmp_path / "outside-repo")


def test_validate_private_output_directory_accepts_each_known_private_root() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    for relative in ("private-media/case", "data/private/case", "media/private/case"):
        _validate_private_output_directory(repository_root / relative)


def test_validate_private_output_directory_accepts_private_root_itself() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    _validate_private_output_directory(repository_root / "private-media")


def test_validate_private_output_directory_rejects_look_alike_root_name() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private directory"):
        _validate_private_output_directory(repository_root / "private-media-decoy" / "case")


def test_diversity_pool_selects_top_window_per_method_and_sorts_by_feature_index() -> None:
    # Each window dominates exactly one method; a fifth window is mid-scoring
    # everywhere and must not survive a per-method limit of one.
    scored = (
        _scored(3, quality=0.1, dynamics=0.1, scenic=0.1, balanced=0.9),
        _scored(1, quality=0.1, dynamics=0.9, scenic=0.1, balanced=0.1),
        _scored(4, quality=0.5, dynamics=0.5, scenic=0.5, balanced=0.5),
        _scored(0, quality=0.9, dynamics=0.1, scenic=0.1, balanced=0.1),
        _scored(2, quality=0.1, dynamics=0.1, scenic=0.9, balanced=0.1),
    )

    pool = _build_diversity_pool(scored, per_method=1)

    assert [item.evidence.feature_index for item in pool] == [1, 4, 7, 10]


def test_diversity_pool_deduplicates_a_window_that_tops_every_method() -> None:
    dominant = _scored(0, quality=0.9, dynamics=0.9, scenic=0.9, balanced=0.9)
    runner_up = _scored(1, quality=0.5, dynamics=0.5, scenic=0.5, balanced=0.5)

    pool = _build_diversity_pool((dominant, runner_up), per_method=1)

    assert len(pool) == 1
    assert pool[0].evidence.feature_index == dominant.evidence.feature_index


def test_write_private_research_state_serializes_counts_selections_and_evaluations(
    tmp_path: Path,
) -> None:
    scored = _scored(0, quality=0.8)
    selection = QualitySelection(
        method=QualitySelectionMethod.QUALITY_FIRST,
        rank=1,
        scored=scored,
        relevance_score=0.8,
        diversity_gain=0.0,
    )
    evaluation = QualitySelectionEvaluation(
        selected_count=1,
        unique_window_count=1,
        aesthetic_mean=0.5,
        aesthetic_minimum=0.5,
        utility_frame_ratio=0.0,
        mean_pairwise_distance=0.0,
        minimum_pairwise_distance=0.0,
        representativeness_distance=0.0,
        natural_scene_probability_mean=0.5,
        built_scene_probability_mean=0.5,
        route_bucket_coverage=1,
        hard_gate_violation_count=0,
    )
    output_path = tmp_path / "state.json"

    _write_private_research_state(
        output_path,
        {QualitySelectionMethod.QUALITY_FIRST: (selection,)},
        {QualitySelectionMethod.QUALITY_FIRST: evaluation},
        analyzed_window_count=10,
        strict_gate_count=4,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "local-highlight-private-state-v1"
    assert payload["privacy"] == {"external_data_sent": False, "private_output": True}
    assert payload["counts"] == {"analyzed_window_count": 10, "strict_gate_count": 4}
    method_payload = payload["methods"]["01-quality-first"]
    assert method_payload["evaluation"]["selected_count"] == 1
    assert method_payload["selections"] == [
        {
            "rank": 1,
            "asset_id": "asset-0",
            "start_offset_s": 0.0,
            "relevance_score": 0.8,
            "diversity_gain": 0.0,
        }
    ]


def test_build_contact_sheet_rejects_empty_thumbnails(tmp_path: Path) -> None:
    with pytest.raises(HighlightResearchError, match="requires selected thumbnails"):
        _build_contact_sheet(
            (),
            tmp_path / "sheet.jpg",
            overwrite=True,
            command_runner=lambda *args, **kwargs: _completed(0),
        )


def test_build_contact_sheet_accepts_a_runner_that_writes_the_output_file(
    tmp_path: Path,
) -> None:
    thumbnail = tmp_path / "clip-01.jpg"
    thumbnail.write_bytes(b"jpg")
    output_path = tmp_path / "sheet.jpg"

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path.write_bytes(b"sheet")
        return _completed(0)

    result = _build_contact_sheet((thumbnail,), output_path, overwrite=True, command_runner=runner)

    assert result == output_path


def test_build_contact_sheet_rejects_nonzero_exit(tmp_path: Path) -> None:
    thumbnail = tmp_path / "clip-01.jpg"
    thumbnail.write_bytes(b"jpg")

    with pytest.raises(HighlightResearchError, match="contact sheet creation failed"):
        _build_contact_sheet(
            (thumbnail,),
            tmp_path / "sheet.jpg",
            overwrite=True,
            command_runner=lambda *args, **kwargs: _completed(1),
        )


def test_build_contact_sheet_rejects_a_missing_output_file_despite_success_code(
    tmp_path: Path,
) -> None:
    thumbnail = tmp_path / "clip-01.jpg"
    thumbnail.write_bytes(b"jpg")

    with pytest.raises(HighlightResearchError, match="contact sheet creation failed"):
        _build_contact_sheet(
            (thumbnail,),
            tmp_path / "sheet.jpg",
            overwrite=True,
            command_runner=lambda *args, **kwargs: _completed(0),
        )


def test_build_complete_evidence_returns_frames_and_center_paths_per_window(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (
        _window("asset-0", timeline_s=0.0, start_offset_s=0.0),
        _window("asset-1", timeline_s=100.0, start_offset_s=20.0),
    )
    source_paths = {
        "asset-0": _write_file(tmp_path / "source-0.mp4", b"source-0"),
        "asset-1": _write_file(tmp_path / "source-1.mp4", b"source-1"),
    }
    proxy_paths = {
        "asset-0": _write_file(tmp_path / "proxy-0.mp4", b"proxy-0"),
        "asset-1": _write_file(tmp_path / "proxy-1.mp4", b"proxy-1"),
    }
    # Each asset's cached sample must actually cover its own window's offset.
    _seed_gpmf_cache(cache, source_paths["asset-0"], (_gpmf_sample(time_s=0.0),))
    _seed_gpmf_cache(cache, source_paths["asset-1"], (_gpmf_sample(time_s=20.0),))
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=2,
        windows=windows,
        source_paths=source_paths,
        proxy_paths=proxy_paths,
    )
    probe_path = output_directory / ".apple-vision-probe"

    evidence, center_frames = _build_complete_evidence(
        windows,
        analysis,
        output_directory,
        metric_cache=cache,
        command_runner=_evidence_command_runner(probe_path),
    )

    assert [item.window.asset_id for item in evidence] == ["asset-0", "asset-1"]
    assert [item.feature_index for item in evidence] == [1, 4]
    assert all(len(item.frames) == 3 for item in evidence)
    assert set(center_frames) == {("asset-0", 0.0), ("asset-1", 20.0)}
    assert all(path.is_file() for path in center_frames.values())


def test_build_complete_evidence_rejects_when_no_asset_has_local_gpmf(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (_window("asset-0", timeline_s=0.0, start_offset_s=0.0),)
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=windows, source_paths={}, proxy_paths={}
    )

    with pytest.raises(HighlightResearchError, match="no strict windows had complete local"):
        _build_complete_evidence(
            windows,
            analysis,
            output_directory,
            metric_cache=cache,
            command_runner=lambda *a, **k: _completed(0),
        )


def test_build_complete_evidence_rejects_when_gpmf_coverage_is_too_thin(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (_window("asset-0", timeline_s=0.0, start_offset_s=0.0),)
    source_path = _write_file(tmp_path / "source-0.mp4")
    # One second of GPMF against a 12-second window is far under the 0.75
    # coverage floor, so the window never becomes eligible.
    _seed_gpmf_cache(cache, source_path, (_gpmf_sample(time_s=0.0, duration_s=1.0),))
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1,
        windows=windows,
        source_paths={"asset-0": source_path},
        proxy_paths={"asset-0": _write_file(tmp_path / "proxy-0.mp4")},
    )

    with pytest.raises(HighlightResearchError, match="no strict windows had complete local"):
        _build_complete_evidence(
            windows,
            analysis,
            output_directory,
            metric_cache=cache,
            command_runner=lambda *a, **k: _completed(0),
        )


def test_build_complete_evidence_rejects_a_missing_proxy(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (_window("asset-0", timeline_s=0.0, start_offset_s=0.0),)
    source_path = _write_file(tmp_path / "source-0.mp4")
    _seed_gpmf_cache(cache, source_path, (_gpmf_sample(),))
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1,
        windows=windows,
        source_paths={"asset-0": source_path},
        proxy_paths={},
    )

    with pytest.raises(HighlightResearchError, match="no local proxy"):
        _build_complete_evidence(
            windows,
            analysis,
            output_directory,
            metric_cache=cache,
            command_runner=lambda *a, **k: _completed(0),
        )


def test_build_complete_evidence_rejects_a_failed_frame_extraction(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (_window("asset-0", timeline_s=0.0, start_offset_s=0.0),)
    source_path = _write_file(tmp_path / "source-0.mp4")
    _seed_gpmf_cache(cache, source_path, (_gpmf_sample(),))
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1,
        windows=windows,
        source_paths={"asset-0": source_path},
        proxy_paths={"asset-0": _write_file(tmp_path / "proxy-0.mp4")},
    )
    probe_path = output_directory / ".apple-vision-probe"

    with pytest.raises(HighlightResearchError, match="frame extraction failed"):
        _build_complete_evidence(
            windows,
            analysis,
            output_directory,
            metric_cache=cache,
            command_runner=_evidence_command_runner(probe_path, frame_extraction_ok=False),
        )


def test_build_complete_evidence_wraps_a_failed_vision_probe_compile(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cache = PrivateMetricCache(output_directory / "metric-cache")
    windows = (_window("asset-0", timeline_s=0.0, start_offset_s=0.0),)
    source_path = _write_file(tmp_path / "source-0.mp4")
    _seed_gpmf_cache(cache, source_path, (_gpmf_sample(),))
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1,
        windows=windows,
        source_paths={"asset-0": source_path},
        proxy_paths={"asset-0": _write_file(tmp_path / "proxy-0.mp4")},
    )
    probe_path = output_directory / ".apple-vision-probe"

    with pytest.raises(HighlightResearchError, match="Apple Vision analysis failed"):
        _build_complete_evidence(
            windows,
            analysis,
            output_directory,
            metric_cache=cache,
            command_runner=_evidence_command_runner(probe_path, probe_compiles=False),
        )


def test_extract_research_clips_writes_a_clip_and_thumbnail(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    source_path = _write_file(tmp_path / "source-0.mp4")
    frame_path = _write_file(tmp_path / "center-0.jpg", b"jpg")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            )
        }
    )

    extracted, thumbnails = _extract_research_clips(
        selections,
        analysis,
        {("asset-0", 0.0): frame_path},
        output_directory,
        overwrite=True,
        command_runner=_clip_command_runner(),
    )

    assert extracted == 1
    assert len(thumbnails) == 1
    assert thumbnails[0].is_file()
    clip_path = output_directory / QualitySelectionMethod.QUALITY_FIRST.value / "clip-01.mp4"
    assert clip_path.is_file()


def test_extract_research_clips_hardlinks_a_window_shared_across_methods(tmp_path: Path) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    source_path = _write_file(tmp_path / "source-0.mp4")
    frame_path = _write_file(tmp_path / "center-0.jpg", b"jpg")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            ),
            QualitySelectionMethod.RIDE_DYNAMICS: (
                _quality_selection(QualitySelectionMethod.RIDE_DYNAMICS, 1, 0),
            ),
        }
    )
    encode_calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        encode_calls.append(command)
        Path(command[-1]).write_bytes(b"clip")
        return _completed(0)

    extracted, thumbnails = _extract_research_clips(
        selections,
        analysis,
        {("asset-0", 0.0): frame_path},
        output_directory,
        overwrite=True,
        command_runner=runner,
    )

    assert extracted == 2
    assert len(thumbnails) == 2
    # The same window is only ever encoded once; its second use is a hardlink.
    assert len(encode_calls) == 1
    first_clip = output_directory / QualitySelectionMethod.QUALITY_FIRST.value / "clip-01.mp4"
    second_clip = output_directory / QualitySelectionMethod.RIDE_DYNAMICS.value / "clip-01.mp4"
    assert first_clip.stat().st_ino == second_clip.stat().st_ino


def test_extract_research_clips_dedup_replaces_a_stale_output_when_overwrite_true(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    source_path = _write_file(tmp_path / "source-0.mp4")
    frame_path = _write_file(tmp_path / "center-0.jpg", b"jpg")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            ),
            QualitySelectionMethod.RIDE_DYNAMICS: (
                _quality_selection(QualitySelectionMethod.RIDE_DYNAMICS, 1, 0),
            ),
        }
    )
    stale_output = output_directory / QualitySelectionMethod.RIDE_DYNAMICS.value / "clip-01.mp4"
    stale_output.parent.mkdir(parents=True)
    stale_output.write_bytes(b"stale")

    _extract_research_clips(
        selections,
        analysis,
        {("asset-0", 0.0): frame_path},
        output_directory,
        overwrite=True,
        command_runner=_clip_command_runner(),
    )

    first_clip = output_directory / QualitySelectionMethod.QUALITY_FIRST.value / "clip-01.mp4"
    assert stale_output.read_bytes() == b"clip"
    assert stale_output.stat().st_ino == first_clip.stat().st_ino


def test_extract_research_clips_dedup_raises_on_a_stale_output_without_overwrite(
    tmp_path: Path,
) -> None:
    # Documents current behavior: the dedup hardlink only clears a stale
    # output when told to overwrite. Left alone, it collides with the
    # pre-existing file instead of silently accepting it.
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    source_path = _write_file(tmp_path / "source-0.mp4")
    frame_path = _write_file(tmp_path / "center-0.jpg", b"jpg")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            ),
            QualitySelectionMethod.RIDE_DYNAMICS: (
                _quality_selection(QualitySelectionMethod.RIDE_DYNAMICS, 1, 0),
            ),
        }
    )
    stale_output = output_directory / QualitySelectionMethod.RIDE_DYNAMICS.value / "clip-01.mp4"
    stale_output.parent.mkdir(parents=True)
    stale_output.write_bytes(b"stale")

    with pytest.raises(FileExistsError):
        _extract_research_clips(
            selections,
            analysis,
            {("asset-0", 0.0): frame_path},
            output_directory,
            overwrite=False,
            command_runner=_clip_command_runner(),
        )


def test_extract_research_clips_rejects_a_missing_source(tmp_path: Path) -> None:
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=0, windows=(), source_paths={}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            )
        }
    )

    with pytest.raises(HighlightResearchError, match="local source is unavailable"):
        _extract_research_clips(
            selections,
            analysis,
            {},
            tmp_path,
            overwrite=True,
            command_runner=lambda *a, **k: _completed(0),
        )


def test_extract_research_clips_rejects_a_failed_encode(tmp_path: Path) -> None:
    source_path = _write_file(tmp_path / "source-0.mp4")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            )
        }
    )

    with pytest.raises(HighlightResearchError, match="clip extraction failed"):
        _extract_research_clips(
            selections,
            analysis,
            {("asset-0", 0.0): tmp_path / "center-0.jpg"},
            tmp_path,
            overwrite=True,
            command_runner=_clip_command_runner(ok=False),
        )


def test_extract_research_clips_rejects_a_missing_center_frame(tmp_path: Path) -> None:
    source_path = _write_file(tmp_path / "source-0.mp4")
    analysis = HighlightWindowAnalysis(
        analyzed_source_count=1, windows=(), source_paths={"asset-0": source_path}, proxy_paths={}
    )
    selections = _all_method_selections(
        {
            QualitySelectionMethod.QUALITY_FIRST: (
                _quality_selection(QualitySelectionMethod.QUALITY_FIRST, 1, 0),
            )
        }
    )

    with pytest.raises(HighlightResearchError, match="no center frame"):
        _extract_research_clips(
            selections,
            analysis,
            {},
            tmp_path,
            overwrite=True,
            command_runner=_clip_command_runner(),
        )
