import json
from pathlib import Path

from app.video.gpmf_metrics import GpmfMetricSample
from app.video.highlight_discovery import VideoMetricSample, analyze_local_highlight_windows
from app.video.inventory import build_local_video_inventory
from app.video.metric_cache import PrivateMetricCache


def _video_sample() -> VideoMetricSample:
    return VideoMetricSample(
        time_s=1.0,
        motion=5.0,
        scene_difference=2.0,
        blur=1.0,
        luma=120.0,
        dynamic_range=180.0,
        saturation=24.0,
        entropy=0.9,
    )


def _gpmf_sample() -> GpmfMetricSample:
    return GpmfMetricSample(
        time_s=1.0,
        duration_s=1.0,
        gyro_sustained_rad_s=0.2,
        gyro_jitter_rad_s=0.1,
        gyro_peak_rad_s=0.4,
        acceleration_jitter_mps2=1.5,
        iso_mean=100.0,
        shutter_mean_s=0.001,
        luma_mean=120.0,
        uniformity_mean=0.2,
        natural_scene_probability=0.7,
        built_scene_probability=0.3,
        scene_confidence=0.6,
        hue_weight_mean=0.5,
    )


def test_video_metric_cache_reuses_derived_metrics_across_instances(tmp_path: Path) -> None:
    source = tmp_path / "private-ride-source.mp4"
    source.write_bytes(b"private-source-content")
    calls = 0

    def analyzer(_path: Path) -> tuple[VideoMetricSample, ...]:
        nonlocal calls
        calls += 1
        return (_video_sample(),)

    first = PrivateMetricCache(tmp_path / "private-cache")
    assert first.load_or_analyze_video_metrics(source, analyzer) == (_video_sample(),)
    second = PrivateMetricCache(tmp_path / "private-cache")
    assert second.load_or_analyze_video_metrics(source, analyzer) == (_video_sample(),)
    assert calls == 1


def test_video_metric_cache_invalidates_when_source_fingerprint_changes(tmp_path: Path) -> None:
    source = tmp_path / "ride.mp4"
    source.write_bytes(b"first source")
    cache = PrivateMetricCache(tmp_path / "private-cache")
    calls = 0

    def analyzer(_path: Path) -> tuple[VideoMetricSample, ...]:
        nonlocal calls
        calls += 1
        return (_video_sample(),)

    cache.load_or_analyze_video_metrics(source, analyzer)
    source.write_bytes(b"changed private source content")
    cache.load_or_analyze_video_metrics(source, analyzer)
    assert calls == 2


def test_gpmf_metric_cache_reuses_derived_metrics(tmp_path: Path) -> None:
    source = tmp_path / "ride.mp4"
    source.write_bytes(b"private-source-content")
    cache = PrivateMetricCache(tmp_path / "private-cache")
    calls = 0

    def analyzer(_path: Path) -> tuple[GpmfMetricSample, ...]:
        nonlocal calls
        calls += 1
        return (_gpmf_sample(),)

    assert cache.load_or_analyze_gpmf_metrics(source, analyzer) == (_gpmf_sample(),)
    assert cache.load_or_analyze_gpmf_metrics(source, analyzer) == (_gpmf_sample(),)
    assert calls == 1


def test_corrupt_metric_cache_is_recomputed_safely(tmp_path: Path) -> None:
    source = tmp_path / "ride.mp4"
    source.write_bytes(b"private-source-content")
    cache_root = tmp_path / "private-cache"
    cache = PrivateMetricCache(cache_root)
    calls = 0

    def analyzer(_path: Path) -> tuple[VideoMetricSample, ...]:
        nonlocal calls
        calls += 1
        return (_video_sample(),)

    cache.load_or_analyze_video_metrics(source, analyzer)
    cache_path = next((cache_root / "video-metrics").glob("*.json"))
    cache_path.write_text("not valid JSON", encoding="utf-8")
    assert cache.load_or_analyze_video_metrics(source, analyzer) == (_video_sample(),)
    assert calls == 2


def test_metric_cache_payload_contains_no_source_identifier(tmp_path: Path) -> None:
    source = tmp_path / "sensitive-ride-name.mp4"
    source.write_bytes(b"private-source-content")
    cache_root = tmp_path / "private-cache"
    cache = PrivateMetricCache(cache_root)
    cache.load_or_analyze_video_metrics(source, lambda _path: (_video_sample(),))

    cache_path = next((cache_root / "video-metrics").glob("*.json"))
    payload = cache_path.read_text(encoding="utf-8")
    parsed = json.loads(payload)
    assert source.name not in payload
    assert str(source) not in payload
    assert "path" not in parsed
    assert "file_name" not in parsed
    assert parsed["samples"][0]["motion"] == 5.0


def test_highlight_window_analysis_uses_the_private_video_metric_cache(tmp_path: Path) -> None:
    video_root = tmp_path / "videos"
    video_root.mkdir()
    source = video_root / "GX010001.MP4"
    source.write_bytes(b"private-source-content")
    inventory = build_local_video_inventory(video_root)
    asset_id = inventory.entries[0].asset_id
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "asset_id": asset_id,
                        "file_name": source.name,
                        "recorded_start_time": "2026-01-01T00:00:00Z",
                        "duration_s": 12,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    points = "\n".join(
        (
            "<trkpt lat=\"-45.0\" lon=\"170.%04d\"><ele>10</ele>"
            "<time>2026-01-01T00:00:%02dZ</time></trkpt>" % (index, index)
        )
        for index in range(13)
    )
    gpx = tmp_path / "route.gpx"
    gpx.write_text(f"<gpx><trk><trkseg>{points}</trkseg></trk></gpx>", encoding="utf-8")
    cache = PrivateMetricCache(tmp_path / "private-cache")
    calls = 0

    def analyzer(_path: Path) -> tuple[VideoMetricSample, ...]:
        nonlocal calls
        calls += 1
        return tuple(
            VideoMetricSample(
                time_s=float(index),
                motion=5.0,
                scene_difference=1.0,
                blur=1.0,
                luma=120.0,
                dynamic_range=180.0,
                saturation=24.0,
                entropy=0.9,
            )
            for index in range(12)
        )

    first = analyze_local_highlight_windows(
        gpx,
        video_root,
        catalog,
        clip_duration_s=12,
        stride_s=2,
        analyzer=analyzer,
        metric_cache=cache,
    )
    second = analyze_local_highlight_windows(
        gpx,
        video_root,
        catalog,
        clip_duration_s=12,
        stride_s=2,
        analyzer=analyzer,
        metric_cache=cache,
    )

    assert len(first.windows) == len(second.windows) == 1
    assert calls == 1
