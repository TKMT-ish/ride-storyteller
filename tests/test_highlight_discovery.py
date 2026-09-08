import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import app.video.highlight_discovery as highlight_discovery_module
from app.contracts import RoutePoint
from app.video.highlight_discovery import (
    HighlightCandidate,
    HighlightMethod,
    WindowFeatures,
    _bearing_degrees,
    _blend,
    _direction_delta,
    _distance_m,
    _exposure_quality,
    _gps_features,
    _normalize,
    _passes_common_interest_gate,
    _percentile,
    _proxy_matches_source_duration,
    _recording_key,
    _std,
    _validate_private_output_directory,
    analyze_video_metrics,
    build_highlight_clip_command,
    discover_and_extract_highlights,
    export_highlight_manifest,
    parse_ffmpeg_metric_output,
    rank_highlight_windows,
)
from app.video.probe import LocalVideoMetadata, VideoProbeError


def _window(
    asset_id: str,
    *,
    timeline_s: float,
    heading: float = 30.0,
    speed: float = 15.0,
    moving_ratio: float = 1.0,
    speed_std: float = 2.0,
    elevation: float = 8.0,
    motion: float = 5.0,
    motion_std: float = 2.0,
    scene: float = 12.0,
    scene_peaks: float = 0.2,
    blur: float = 5.0,
    luma: float = 128.0,
    dynamic_range: float = 150.0,
    saturation: float = 24.0,
    entropy: float = 0.92,
) -> WindowFeatures:
    return WindowFeatures(
        asset_id=asset_id,
        start_offset_s=30.0,
        duration_s=12.0,
        timeline_s=timeline_s,
        mean_speed_mps=speed,
        minimum_speed_mps=speed,
        speed_p10_mps=speed,
        center_speed_mps=speed,
        moving_ratio=moving_ratio,
        heading_change_degrees=heading,
        center_heading_change_degrees=heading,
        accumulated_heading_change_degrees=heading,
        path_efficiency=0.95,
        speed_std_mps=speed_std,
        speed_range_mps=speed_std * 2,
        elevation_change_m=elevation,
        elevation_range_m=abs(elevation) + 2,
        motion_mean=motion,
        motion_std=motion_std,
        scene_change_mean=scene,
        scene_change_peak_ratio=scene_peaks,
        blur_mean=blur,
        luma_mean=luma,
        dynamic_range_mean=dynamic_range,
        saturation_mean=saturation,
        entropy_mean=entropy,
    )


def test_ranking_produces_ten_methods_and_excludes_stopped_and_straight() -> None:
    usable = tuple(
        _window(
            f"good-{index}",
            timeline_s=index * 60,
            heading=20 + index * 5,
            speed_std=1 + index,
            elevation=index * 3,
            motion=2 + index,
            scene=8 + index,
            saturation=18 + index,
        )
        for index in range(1, 6)
    )
    stopped = _window("stopped", timeline_s=500, speed=0.2, moving_ratio=0.1)
    straight = _window("straight", timeline_s=600, heading=2.0)
    motionless = _window("motionless", timeline_s=700, motion=0.2)

    ranked = rank_highlight_windows(usable + (stopped, straight, motionless), top_k=2)

    assert set(ranked) == set(HighlightMethod)
    assert all(len(candidates) == 2 for candidates in ranked.values())
    assert all(
        candidate.asset_id not in {"stopped", "straight", "motionless"}
        for candidates in ranked.values()
        for candidate in candidates
    )


def test_ranking_keeps_method_candidates_temporally_separated() -> None:
    windows = (
        _window("best", timeline_s=0, heading=80),
        _window("nearby", timeline_s=10, heading=70),
        _window("later", timeline_s=80, heading=60),
    )

    ranked = rank_highlight_windows(windows, top_k=2, min_separation_s=30)

    assert [candidate.asset_id for candidate in ranked[HighlightMethod.GPS_CURVES]] == [
        "best",
        "later",
    ]


def test_ffmpeg_metric_parser_reads_frames_and_expected_values() -> None:
    output = """frame:0 pts:0 pts_time:0
lavfi.signalstats.YAVG=120.5
lavfi.signalstats.YLOW=20
lavfi.signalstats.YHIGH=220
lavfi.signalstats.SATAVG=25
lavfi.entropy.normalized_entropy.normal.Y=0.91
lavfi.blur=4.5
lavfi.vmafmotion.score=0.0
frame:1 pts:1 pts_time:1
lavfi.signalstats.YAVG=122.5
lavfi.signalstats.YLOW=22
lavfi.signalstats.YHIGH=218
lavfi.signalstats.SATAVG=27
lavfi.signalstats.YDIF=14
lavfi.entropy.normalized_entropy.normal.Y=0.93
lavfi.blur=4.0
lavfi.vmafmotion.score=6.0
"""

    samples = parse_ffmpeg_metric_output(output)

    assert len(samples) == 2
    assert samples[1].time_s == 1
    assert samples[1].motion == 6
    assert samples[1].scene_difference == 14
    assert samples[1].dynamic_range == 196


def test_mp4_metric_analysis_downscales_locally_when_lrv_is_unavailable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "GX010001.MP4"
    source.write_bytes(b"source")
    output = """frame:0 pts:0 pts_time:0
lavfi.signalstats.YAVG=120
lavfi.signalstats.YLOW=20
lavfi.signalstats.YHIGH=220
lavfi.signalstats.SATAVG=25
lavfi.entropy.normalized_entropy.normal.Y=0.91
lavfi.blur=4.5
lavfi.vmafmotion.score=6.0
"""
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], **_kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout=output, stderr="")

    samples = analyze_video_metrics(source, runner=runner)

    assert len(samples) == 1
    assert commands[0][commands[0].index("-i") + 1] == str(source)
    assert "fps=1,scale=320:-2" in commands[0][commands[0].index("-vf") + 1]


def test_highlight_manifest_has_no_path_coordinate_or_timestamp_fields() -> None:
    manifest = export_highlight_manifest(
        {
            HighlightMethod.GPS_CURVES: (
                HighlightCandidate(
                    method=HighlightMethod.GPS_CURVES,
                    rank=1,
                    asset_id="local-video-abc",
                    start_offset_s=10,
                    duration_s=12,
                    score=0.9,
                    output_file_name="clip-01.mp4",
                ),
            )
        },
        analyzed_window_count=20,
        eligible_window_count=5,
    )

    assert "latitude" not in manifest
    assert "longitude" not in manifest
    assert '"absolute_path":' not in manifest
    assert "/Users/" not in manifest
    assert "recorded_start_time" not in manifest
    assert json.loads(manifest)["privacy"]["external_data_sent"] is False


def test_highlight_clip_command_uses_one_local_input_and_720p_output(tmp_path: Path) -> None:
    source = tmp_path / "source with spaces.mp4"
    output = tmp_path / "clip.mp4"

    command = build_highlight_clip_command(
        source,
        output,
        start_offset_s=15.0,
        duration_s=12.0,
        overwrite=False,
    )

    assert command[command.index("-i") + 1] == str(source)
    assert "scale=-2:720" in command
    assert command[-1] == str(output)


def test_highlight_discovery_rejects_unignored_repository_output() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private directory"):
        discover_and_extract_highlights(
            Path("missing.gpx"),
            Path("missing-videos"),
            Path("missing-catalog.json"),
            repository_root / "unsafe-highlight-output",
        )


# ---------------------------------------------------------------------------
# _proxy_matches_source_duration
#
# Real-media testing on 2026-09-02 found that `_recording_key` can pair an
# unrelated, much shorter .LRV to an .MP4 that merely shares its numeric
# suffix (see docs/current-system-handoff-ja.md). These tests cover the
# duration check added to reject that mismatch.
# ---------------------------------------------------------------------------


def _metadata(duration_s: float) -> LocalVideoMetadata:
    return LocalVideoMetadata(
        file_name="proxy.LRV",
        duration_s=duration_s,
        recorded_start_time=datetime(2026, 1, 1, tzinfo=UTC),
        video_codec="hevc",
        width=1920,
        height=1080,
        frames_per_second=30.0,
        has_audio=False,
    )


def test_proxy_matches_source_duration_accepts_a_proxy_covering_the_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        highlight_discovery_module, "probe_local_video_metadata", lambda path: _metadata(275.4)
    )

    assert _proxy_matches_source_duration(tmp_path / "proxy.LRV", 275.4) is True


def test_proxy_matches_source_duration_accepts_within_tolerance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        highlight_discovery_module, "probe_local_video_metadata", lambda path: _metadata(273.0)
    )

    assert _proxy_matches_source_duration(tmp_path / "proxy.LRV", 275.4) is True


def test_proxy_matches_source_duration_rejects_a_much_shorter_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Reproduces the real case: a 44s .LRV coincidentally sharing a chapter
    # number with a 275s .MP4 it does not correspond to.
    monkeypatch.setattr(
        highlight_discovery_module, "probe_local_video_metadata", lambda path: _metadata(44.16)
    )

    assert _proxy_matches_source_duration(tmp_path / "proxy.LRV", 275.4) is False


def test_proxy_matches_source_duration_rejects_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(path: Path) -> LocalVideoMetadata:
        raise VideoProbeError("simulated probe failure")

    monkeypatch.setattr(highlight_discovery_module, "probe_local_video_metadata", fail)

    assert _proxy_matches_source_duration(tmp_path / "proxy.LRV", 275.4) is False


# ---------------------------------------------------------------------------
# Footage without a proxy
#
# Not every camera writes a low-resolution proxy beside its recording, and a
# product that processes other people's rides cannot assume one. The window
# analysis already falls back to the full-resolution source when no proxy
# pairs with it -- but the entry point's default analyser accepted LRV files
# only, so the fallback handed it a file it refused.
# ---------------------------------------------------------------------------


def test_the_default_analyser_reads_footage_that_has_no_proxy(tmp_path: Path) -> None:
    import inspect
    import subprocess as _subprocess

    from app.video.highlight_discovery import analyze_video_metrics

    default = inspect.signature(discover_and_extract_highlights).parameters["analyzer"].default
    analyser = default if default is not None else analyze_video_metrics

    source = tmp_path / "GH010001.mp4"
    source.write_bytes(b"")
    metrics = """frame:0 pts:0 pts_time:0
lavfi.signalstats.YAVG=120.5
lavfi.signalstats.YLOW=20
lavfi.signalstats.YHIGH=220
lavfi.signalstats.SATAVG=25
lavfi.entropy.normalized_entropy.normal.Y=0.91
lavfi.blur=4.5
lavfi.vmafmotion.score=0.0
"""

    seen: list[str] = []

    def stub(command, **_kwargs) -> _subprocess.CompletedProcess[str]:
        seen.append(str(command[command.index("-i") + 1]))
        return _subprocess.CompletedProcess(args=(), returncode=0, stdout=metrics, stderr="")

    samples = analyser(source, runner=stub)

    # The source itself was analysed: no proxy was required to reach it.
    assert seen == [str(source)]
    assert len(samples) == 1


# ---------------------------------------------------------------------------
# Pure scoring and geometry helpers (no real media, no GPS coordinates that
# could identify a place -- every fixture below is a synthetic number).
# ---------------------------------------------------------------------------


def test_normalize_maps_min_and_max_to_zero_and_one() -> None:
    assert _normalize([10.0, 20.0, 30.0]) == pytest.approx([0.0, 0.5, 1.0])


def test_normalize_returns_midpoint_for_equal_values() -> None:
    assert _normalize([4.0, 4.0, 4.0]) == pytest.approx([0.5, 0.5, 0.5])


def test_normalize_returns_empty_for_empty_input() -> None:
    assert _normalize([]) == []


def test_blend_weights_values_by_their_relative_weight() -> None:
    blended = _blend(([0.0, 1.0], 1.0), ([1.0, 1.0], 3.0))

    assert blended == pytest.approx([0.75, 1.0])


def test_blend_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        _blend(([0.0, 1.0], 1.0), ([1.0], 1.0))


def test_blend_rejects_non_positive_total_weight() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _blend(([0.0, 1.0], 1.0), ([1.0, 1.0], -1.0))


def test_blend_returns_empty_for_no_inputs() -> None:
    assert _blend() == []


def test_exposure_quality_is_perfect_at_middle_gray_and_full_range() -> None:
    window = _window("a", timeline_s=0.0, luma=128.0, dynamic_range=180.0)

    assert _exposure_quality(window) == pytest.approx(1.0)


def test_exposure_quality_penalizes_clipped_blacks_and_flat_range() -> None:
    window = _window("a", timeline_s=0.0, luma=0.0, dynamic_range=0.0)

    assert _exposure_quality(window) == pytest.approx(0.0)


def test_exposure_quality_clamps_dynamic_range_above_the_reference() -> None:
    reference = _window("a", timeline_s=0.0, luma=128.0, dynamic_range=180.0)
    saturated = _window("a", timeline_s=0.0, luma=128.0, dynamic_range=360.0)

    assert _exposure_quality(saturated) == pytest.approx(_exposure_quality(reference))


def test_recording_key_strips_the_two_letter_gopro_prefix() -> None:
    assert _recording_key("GH010102.MP4") == "010102"


def test_recording_key_is_case_insensitive() -> None:
    assert _recording_key("gh010102.mp4") == _recording_key("GH010102.MP4")


def test_recording_key_keeps_names_that_do_not_start_with_g() -> None:
    assert _recording_key("IMG_1234.MP4") == "IMG_1234"


def test_recording_key_keeps_short_stems_unchanged() -> None:
    assert _recording_key("GA.MP4") == "GA"


def test_std_is_zero_for_fewer_than_two_samples() -> None:
    assert _std([]) == 0.0
    assert _std([5.0]) == 0.0


def test_std_matches_population_standard_deviation_for_two_or_more() -> None:
    assert _std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.0)


def _route_point(
    *,
    timestamp: datetime,
    latitude: float,
    longitude: float,
    speed_mps: float | None,
    elevation_m: float | None = None,
    distance_from_start_m: float = 0.0,
) -> RoutePoint:
    return RoutePoint(
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation_m,
        distance_from_start_m=distance_from_start_m,
        speed_mps=speed_mps,
    )


def test_distance_m_between_one_degree_of_latitude_matches_known_earth_radius() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    south = _route_point(timestamp=base, latitude=0.0, longitude=0.0, speed_mps=0.0)
    north = _route_point(timestamp=base, latitude=1.0, longitude=0.0, speed_mps=0.0)

    assert _distance_m(south, north) == pytest.approx(111_195.0, rel=1e-3)


def test_distance_m_is_zero_for_the_same_point() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    point = _route_point(timestamp=base, latitude=12.0, longitude=34.0, speed_mps=0.0)

    assert _distance_m(point, point) == pytest.approx(0.0, abs=1e-6)


def test_bearing_degrees_points_due_north_and_due_east() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    origin = _route_point(timestamp=base, latitude=0.0, longitude=0.0, speed_mps=0.0)
    north = _route_point(timestamp=base, latitude=1.0, longitude=0.0, speed_mps=0.0)
    east = _route_point(timestamp=base, latitude=0.0, longitude=1.0, speed_mps=0.0)

    assert _bearing_degrees(origin, north) == pytest.approx(0.0, abs=1e-6)
    assert _bearing_degrees(origin, east) == pytest.approx(90.0, abs=1e-6)


def test_direction_delta_takes_the_shorter_way_around_the_compass() -> None:
    assert _direction_delta(350.0, 10.0) == pytest.approx(20.0)
    assert _direction_delta(10.0, 350.0) == pytest.approx(20.0)


def test_direction_delta_is_zero_for_the_same_heading() -> None:
    assert _direction_delta(45.0, 45.0) == 0.0


def test_direction_delta_caps_at_a_half_turn() -> None:
    assert _direction_delta(0.0, 180.0) == pytest.approx(180.0)


def test_percentile_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="values are required"):
        _percentile([], 0.5)


def test_percentile_rejects_fraction_outside_zero_and_one() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        _percentile([1.0, 2.0], -0.1)
    with pytest.raises(ValueError, match="between zero and one"):
        _percentile([1.0, 2.0], 1.1)


def test_percentile_at_zero_and_one_returns_the_endpoints() -> None:
    values = [1.0, 2.0, 3.0, 4.0]

    assert _percentile(values, 0.0) == 1.0
    assert _percentile(values, 1.0) == 4.0


def test_percentile_interpolates_between_the_bracketing_values() -> None:
    assert _percentile([0.0, 10.0], 0.25) == pytest.approx(2.5)


def test_passes_common_interest_gate_accepts_the_default_synthetic_window() -> None:
    assert _passes_common_interest_gate(_window("a", timeline_s=0.0)) is True


def test_passes_common_interest_gate_rejects_slow_windows() -> None:
    window = _window("a", timeline_s=0.0, speed=4.9)

    assert _passes_common_interest_gate(window) is False


def test_passes_common_interest_gate_rejects_mostly_stopped_windows() -> None:
    window = _window("a", timeline_s=0.0, moving_ratio=0.84)

    assert _passes_common_interest_gate(window) is False


def test_passes_common_interest_gate_rejects_straight_roads() -> None:
    window = _window("a", timeline_s=0.0, heading=7.9)

    assert _passes_common_interest_gate(window) is False


def test_passes_common_interest_gate_rejects_static_looking_footage() -> None:
    window = _window("a", timeline_s=0.0, motion=4.9)

    assert _passes_common_interest_gate(window) is False


def test_validate_private_output_directory_allows_paths_outside_the_repository(
    tmp_path: Path,
) -> None:
    # A path that never resolves under the repository root (e.g. a caller's own
    # tmp directory) is not this guard's concern -- it silently allows it.
    _validate_private_output_directory(tmp_path / "anywhere")


def test_validate_private_output_directory_rejects_unignored_repository_paths() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="ignored private directory"):
        _validate_private_output_directory(repository_root / "unsafe-output")


def test_validate_private_output_directory_accepts_each_known_private_root() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    for relative in ("private-media/case", "data/private/case", "media/private/case"):
        _validate_private_output_directory(repository_root / relative)


# ---------------------------------------------------------------------------
# _gps_features
# ---------------------------------------------------------------------------


def test_gps_features_returns_none_when_fewer_than_two_points_are_in_range() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    points = (_route_point(timestamp=base, latitude=0.0, longitude=0.0, speed_mps=5.0),)
    timestamps = (base.timestamp(),)

    result = _gps_features(points, timestamps, base, base + timedelta(seconds=12))

    assert result is None


def test_gps_features_returns_none_when_fewer_than_two_speed_samples_exist() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    points = tuple(
        _route_point(
            timestamp=base + timedelta(seconds=offset),
            latitude=offset * 0.0001,
            longitude=0.0,
            speed_mps=5.0 if offset == 0 else None,
        )
        for offset in range(4)
    )
    timestamps = tuple(point.timestamp.timestamp() for point in points)

    result = _gps_features(points, timestamps, base, base + timedelta(seconds=3))

    assert result is None


def test_gps_features_computes_motion_and_defaults_elevation_without_two_samples() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # A straight line heading due north at a steady 10 m/s; no elevation
    # recorded, which the function must default to zero change rather than
    # raise on.
    points = tuple(
        _route_point(
            timestamp=base + timedelta(seconds=offset),
            latitude=offset * 0.0001,
            longitude=0.0,
            speed_mps=10.0,
        )
        for offset in range(12)
    )
    timestamps = tuple(point.timestamp.timestamp() for point in points)

    result = _gps_features(points, timestamps, base, base + timedelta(seconds=11))

    assert result is not None
    assert result["mean_speed_mps"] == pytest.approx(10.0)
    assert result["moving_ratio"] == pytest.approx(1.0)
    assert result["elevation_change_m"] == 0.0
    assert result["elevation_range_m"] == 0.0
    assert result["latitude"] == points[len(points) // 2].latitude


def test_gps_features_reports_elevation_change_when_two_samples_exist() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    points = tuple(
        _route_point(
            timestamp=base + timedelta(seconds=offset),
            latitude=offset * 0.0001,
            longitude=0.0,
            speed_mps=10.0,
            elevation_m=100.0 + offset * 2.0,
        )
        for offset in range(12)
    )
    timestamps = tuple(point.timestamp.timestamp() for point in points)

    result = _gps_features(points, timestamps, base, base + timedelta(seconds=11))

    assert result is not None
    assert result["elevation_change_m"] == pytest.approx(22.0)
    assert result["elevation_range_m"] == pytest.approx(22.0)


def test_gps_features_reports_a_heading_change_for_a_turning_path() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Heads due north up to the window's midpoint, then turns to head due
    # east for the second half -- a clean 90 degree corner at the midpoint.
    corner_offset = 6
    points = []
    for offset in range(corner_offset + 1):
        points.append(
            _route_point(
                timestamp=base + timedelta(seconds=offset),
                latitude=offset * 0.001,
                longitude=0.0,
                speed_mps=10.0,
            )
        )
    corner_latitude = points[-1].latitude
    for offset in range(corner_offset + 1, corner_offset * 2 + 1):
        points.append(
            _route_point(
                timestamp=base + timedelta(seconds=offset),
                latitude=corner_latitude,
                longitude=(offset - corner_offset) * 0.001,
                speed_mps=10.0,
            )
        )
    points = tuple(points)
    timestamps = tuple(point.timestamp.timestamp() for point in points)

    result = _gps_features(points, timestamps, base, base + timedelta(seconds=corner_offset * 2))

    assert result is not None
    assert result["heading_change_degrees"] == pytest.approx(90.0, abs=1e-6)
