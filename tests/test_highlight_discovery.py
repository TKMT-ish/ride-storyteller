import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import app.video.highlight_discovery as highlight_discovery_module
from app.video.highlight_discovery import (
    HighlightCandidate,
    HighlightMethod,
    WindowFeatures,
    _proxy_matches_source_duration,
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
