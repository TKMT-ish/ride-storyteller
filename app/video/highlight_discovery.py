"""Discover varied local highlight candidates without uploading private media.

The discovery pass analyzes GoPro LRV proxies with FFmpeg at one frame per second,
joins those visual signals to private GPX motion features, and extracts comparison
clips from the corresponding MP4 sources. It deliberately does not confirm visual
evidence: every output remains a human-review candidate.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from statistics import fmean, pstdev
from typing import TYPE_CHECKING

from app.contracts import RoutePoint
from app.gps import parse_gpx

from .catalog import VideoCatalogEntry, load_video_catalog
from .inventory import build_local_video_inventory
from .probe import VideoProbeError, probe_local_video_metadata

if TYPE_CHECKING:
    from .metric_cache import PrivateMetricCache

HIGHLIGHT_MANIFEST_SCHEMA_VERSION = "local-highlight-comparison-v1"
DEFAULT_CLIP_DURATION_S = 12.0
DEFAULT_WINDOW_STRIDE_S = 6.0
DEFAULT_TOP_K = 3
MIN_MEAN_SPEED_MPS = 5.0
MIN_MOVING_RATIO = 0.85
MIN_HEADING_CHANGE_DEGREES = 8.0
MIN_VISUAL_MOTION = 5.0
_PRIVATE_REPOSITORY_OUTPUT_ROOTS = (
    Path("private-media"),
    Path("data/private"),
    Path("media/private"),
)


class HighlightDiscoveryError(RuntimeError):
    """Raised when private highlight analysis or extraction fails safely."""


class HighlightMethod(StrEnum):
    GPS_CURVES = "01-gps-curves"
    GPS_SPEED_DYNAMICS = "02-gps-speed-dynamics"
    GPS_ELEVATION_DYNAMICS = "03-gps-elevation-dynamics"
    VISUAL_MOTION = "04-visual-motion"
    SCENE_VARIATION = "05-scene-variation"
    SHARPNESS = "06-sharpness"
    EXPOSURE = "07-exposure"
    COLOR_RICHNESS = "08-color-richness"
    VISUAL_COMPLEXITY = "09-visual-complexity"
    CINEMATIC_COMPOSITE = "10-cinematic-composite"


METHOD_DESCRIPTIONS: dict[HighlightMethod, str] = {
    HighlightMethod.GPS_CURVES: "走行中の方位変化が大きいカーブを優先",
    HighlightMethod.GPS_SPEED_DYNAMICS: "停車を除外し、速度変化のある区間を優先",
    HighlightMethod.GPS_ELEVATION_DYNAMICS: "短時間の高低差や勾配変化を優先",
    HighlightMethod.VISUAL_MOTION: "VMAF motionが高く変化のある映像を優先",
    HighlightMethod.SCENE_VARIATION: "フレーム差と場面変化が大きい区間を優先",
    HighlightMethod.SHARPNESS: "動きのある区間から低blur・高entropyを優先",
    HighlightMethod.EXPOSURE: "黒つぶれ・白飛びが少なく階調幅のある映像を優先",
    HighlightMethod.COLOR_RICHNESS: "彩度が高く色のある映像を優先",
    HighlightMethod.VISUAL_COMPLEXITY: "entropyと階調幅が高い情報量の多い映像を優先",
    HighlightMethod.CINEMATIC_COMPOSITE: "GPSと映像の全指標を統合し時刻分散も確保",
}


@dataclass(frozen=True)
class VideoMetricSample:
    time_s: float
    motion: float
    scene_difference: float
    blur: float
    luma: float
    dynamic_range: float
    saturation: float
    entropy: float


@dataclass(frozen=True)
class WindowFeatures:
    asset_id: str
    start_offset_s: float
    duration_s: float
    timeline_s: float
    mean_speed_mps: float
    minimum_speed_mps: float
    speed_p10_mps: float
    center_speed_mps: float
    moving_ratio: float
    heading_change_degrees: float
    center_heading_change_degrees: float
    accumulated_heading_change_degrees: float
    path_efficiency: float
    speed_std_mps: float
    speed_range_mps: float
    elevation_change_m: float
    elevation_range_m: float
    motion_mean: float
    motion_std: float
    scene_change_mean: float
    scene_change_peak_ratio: float
    blur_mean: float
    luma_mean: float
    dynamic_range_mean: float
    saturation_mean: float
    entropy_mean: float
    # The route point nearest this window's midpoint. Optional and defaulted
    # so existing callers and fixtures are unaffected; only the real
    # `_features_for_source` builder populates it. `timeline_s` is already an
    # absolute GPS-clock Unix timestamp, so together with `duration_s` these
    # two fields let a window be placed on the route without re-deriving
    # anything from source paths or file names.
    latitude: float | None = None
    longitude: float | None = None

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("window asset_id is required")
        if self.start_offset_s < 0 or self.duration_s <= 0:
            raise ValueError("window offsets must define a positive interval")
        if not 0 <= self.moving_ratio <= 1:
            raise ValueError("moving_ratio must be between zero and one")
        if not 0 <= self.path_efficiency <= 1:
            raise ValueError("path_efficiency must be between zero and one")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("window latitude and longitude must be set together")


@dataclass(frozen=True)
class HighlightCandidate:
    method: HighlightMethod
    rank: int
    asset_id: str
    start_offset_s: float
    duration_s: float
    score: float
    output_file_name: str

    def __post_init__(self) -> None:
        if self.rank <= 0 or not self.asset_id or not self.output_file_name:
            raise ValueError("highlight candidate identifiers are required")
        if self.start_offset_s < 0 or self.duration_s <= 0:
            raise ValueError("highlight candidate interval must be positive")
        if not 0 <= self.score <= 1:
            raise ValueError("highlight candidate score must be between zero and one")
        if Path(self.output_file_name).name != self.output_file_name:
            raise ValueError("highlight output must be a file name")

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "asset_id": self.asset_id,
            "start_offset_s": self.start_offset_s,
            "duration_s": self.duration_s,
            "score": self.score,
            "output_file_name": self.output_file_name,
        }


@dataclass(frozen=True)
class HighlightDiscoveryResult:
    analyzed_source_count: int
    analyzed_window_count: int
    eligible_window_count: int
    extracted_clip_count: int
    candidates: dict[HighlightMethod, tuple[HighlightCandidate, ...]]

    def to_dict(self) -> dict[str, object]:
        return {
            "analyzed_source_count": self.analyzed_source_count,
            "analyzed_window_count": self.analyzed_window_count,
            "eligible_window_count": self.eligible_window_count,
            "extracted_clip_count": self.extracted_clip_count,
            "method_count": len(self.candidates),
            "external_data_sent": False,
            "visual_evidence_auto_confirmed": False,
        }


@dataclass(frozen=True)
class HighlightWindowAnalysis:
    analyzed_source_count: int
    windows: tuple[WindowFeatures, ...]
    source_paths: dict[str, Path]
    proxy_paths: dict[str, Path]


def analyze_local_highlight_windows(
    gpx_path: Path,
    video_root: Path,
    catalog_path: Path,
    *,
    clip_duration_s: float = DEFAULT_CLIP_DURATION_S,
    stride_s: float = DEFAULT_WINDOW_STRIDE_S,
    analyzer: Callable[[Path], tuple[VideoMetricSample, ...]] | None = None,
    metric_cache: PrivateMetricCache | None = None,
) -> HighlightWindowAnalysis:
    """Collect reusable local GPS/video windows without extracting clips."""
    if clip_duration_s <= 0 or stride_s <= 0:
        raise ValueError("clip duration and stride must be positive")
    metric_analyzer = analyzer or analyze_video_metrics
    route = parse_gpx(gpx_path)
    catalog = load_video_catalog(catalog_path)
    inventory = build_local_video_inventory(video_root)
    resolved_root = video_root.resolve()
    source_paths = {
        entry.asset_id: resolved_root.joinpath(*entry.relative_path.split("/"))
        for entry in inventory.entries
        if entry.extension in {".mp4", ".mov"}
    }
    proxies_by_key = {
        _recording_key(entry.file_name): resolved_root.joinpath(*entry.relative_path.split("/"))
        for entry in inventory.entries
        if entry.extension == ".lrv"
    }

    route_points = route.points
    route_timestamps = tuple(point.timestamp.timestamp() for point in route_points)
    windows: list[WindowFeatures] = []
    analyzed_source_count = 0
    proxy_paths: dict[str, Path] = {}
    for entry in catalog.entries:
        source_path = source_paths.get(entry.asset_id)
        if source_path is None:
            continue
        candidate_proxy = proxies_by_key.get(_recording_key(entry.file_name))
        analysis_path = (
            candidate_proxy
            if candidate_proxy is not None
            and _proxy_matches_source_duration(candidate_proxy, entry.duration_s)
            else source_path
        )
        samples = (
            metric_cache.load_or_analyze_video_metrics(analysis_path, metric_analyzer)
            if metric_cache is not None
            else metric_analyzer(analysis_path)
        )
        analyzed_source_count += 1
        proxy_paths[entry.asset_id] = analysis_path
        windows.extend(
            _features_for_source(
                entry,
                catalog.video_to_gps_offset_s,
                samples,
                route_points,
                route_timestamps,
                clip_duration_s=clip_duration_s,
                stride_s=stride_s,
            )
        )
    if analyzed_source_count == 0 or not windows:
        raise HighlightDiscoveryError("no paired local source/proxy windows were analyzable")
    return HighlightWindowAnalysis(
        analyzed_source_count=analyzed_source_count,
        windows=tuple(windows),
        source_paths=source_paths,
        proxy_paths=proxy_paths,
    )


def parse_ffmpeg_metric_output(output: str) -> tuple[VideoMetricSample, ...]:
    """Parse metadata=print output from the local FFmpeg metric chain."""
    frames: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("frame:"):
            if current is not None:
                frames.append(current)
            match = re.search(r"pts_time:([-+0-9.eE]+)", line)
            current = {"time": float(match.group(1))} if match else None
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        try:
            current[key] = float(value)
        except ValueError:
            continue
    if current is not None:
        frames.append(current)

    samples: list[VideoMetricSample] = []
    for frame in frames:
        required = (
            "time",
            "lavfi.signalstats.YAVG",
            "lavfi.signalstats.YLOW",
            "lavfi.signalstats.YHIGH",
            "lavfi.signalstats.SATAVG",
            "lavfi.entropy.normalized_entropy.normal.Y",
            "lavfi.blur",
            "lavfi.vmafmotion.score",
        )
        if any(key not in frame for key in required):
            continue
        samples.append(
            VideoMetricSample(
                time_s=frame["time"],
                motion=frame["lavfi.vmafmotion.score"],
                scene_difference=frame.get("lavfi.signalstats.YDIF", 0.0),
                blur=frame["lavfi.blur"],
                luma=frame["lavfi.signalstats.YAVG"],
                dynamic_range=(frame["lavfi.signalstats.YHIGH"] - frame["lavfi.signalstats.YLOW"]),
                saturation=frame["lavfi.signalstats.SATAVG"],
                entropy=frame["lavfi.entropy.normalized_entropy.normal.Y"],
            )
        )
    return tuple(samples)


def analyze_lrv_metrics(
    path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[VideoMetricSample, ...]:
    """Analyze one local LRV proxy at one frame per second."""
    if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".lrv":
        raise ValueError("analysis input must be an existing non-symlink LRV file")
    return analyze_video_metrics(path, runner=runner)


def analyze_video_metrics(
    path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[VideoMetricSample, ...]:
    """Analyze a local LRV, MP4, or MOV at one frame per second.

    Full-resolution sources use the same early 320-pixel downscale as LRV input.
    No frames or metrics leave the local process.
    """
    if (
        not path.is_file()
        or path.is_symlink()
        or path.suffix.lower() not in {".lrv", ".mp4", ".mov"}
    ):
        raise ValueError("analysis input must be an existing non-symlink local video")
    command = (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        ("fps=1,scale=320:-2,signalstats,entropy,blurdetect,vmafmotion,metadata=print:file=-"),
        "-an",
        "-f",
        "null",
        "-",
    )
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise HighlightDiscoveryError("local video analysis could not run") from error
    if completed.returncode != 0:
        raise HighlightDiscoveryError("local video analysis failed")
    samples = parse_ffmpeg_metric_output(completed.stdout)
    if not samples:
        raise HighlightDiscoveryError("local video analysis returned no metric samples")
    return samples


def rank_highlight_windows(
    windows: tuple[WindowFeatures, ...],
    *,
    top_k: int = DEFAULT_TOP_K,
    min_separation_s: float = 30.0,
) -> dict[HighlightMethod, tuple[HighlightCandidate, ...]]:
    """Rank eligible moving, non-straight windows by ten independent methods."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if min_separation_s < 0:
        raise ValueError("min_separation_s must not be negative")
    eligible = tuple(window for window in windows if _passes_common_interest_gate(window))
    if not eligible:
        return {method: () for method in HighlightMethod}

    metrics = {
        "heading": _normalize([w.heading_change_degrees for w in eligible]),
        "speed_std": _normalize([w.speed_std_mps for w in eligible]),
        "speed_range": _normalize([w.speed_range_mps for w in eligible]),
        "elevation_change": _normalize([abs(w.elevation_change_m) for w in eligible]),
        "elevation_range": _normalize([w.elevation_range_m for w in eligible]),
        "motion": _normalize([w.motion_mean for w in eligible]),
        "motion_std": _normalize([w.motion_std for w in eligible]),
        "scene": _normalize([w.scene_change_mean for w in eligible]),
        "scene_peaks": _normalize([w.scene_change_peak_ratio for w in eligible]),
        "blur": _normalize([w.blur_mean for w in eligible]),
        "exposure": [_exposure_quality(w) for w in eligible],
        "dynamic_range": _normalize([w.dynamic_range_mean for w in eligible]),
        "saturation": _normalize([w.saturation_mean for w in eligible]),
        "entropy": _normalize([w.entropy_mean for w in eligible]),
    }
    scores: dict[HighlightMethod, list[float]] = {
        HighlightMethod.GPS_CURVES: metrics["heading"],
        HighlightMethod.GPS_SPEED_DYNAMICS: _blend(
            (metrics["speed_std"], 0.65), (metrics["speed_range"], 0.35)
        ),
        HighlightMethod.GPS_ELEVATION_DYNAMICS: _blend(
            (metrics["elevation_change"], 0.55), (metrics["elevation_range"], 0.45)
        ),
        HighlightMethod.VISUAL_MOTION: _blend(
            (metrics["motion"], 0.65), (metrics["motion_std"], 0.35)
        ),
        HighlightMethod.SCENE_VARIATION: _blend(
            (metrics["scene"], 0.65), (metrics["scene_peaks"], 0.35)
        ),
        HighlightMethod.SHARPNESS: _blend(
            ([1 - value for value in metrics["blur"]], 0.65),
            (metrics["entropy"], 0.35),
        ),
        HighlightMethod.EXPOSURE: _blend(
            (metrics["exposure"], 0.7), (metrics["dynamic_range"], 0.3)
        ),
        HighlightMethod.COLOR_RICHNESS: _blend(
            (metrics["saturation"], 0.75), (metrics["entropy"], 0.25)
        ),
        HighlightMethod.VISUAL_COMPLEXITY: _blend(
            (metrics["entropy"], 0.65), (metrics["dynamic_range"], 0.35)
        ),
        HighlightMethod.CINEMATIC_COMPOSITE: _blend(
            (metrics["heading"], 0.20),
            (metrics["speed_std"], 0.08),
            (metrics["elevation_range"], 0.08),
            (metrics["motion"], 0.14),
            (metrics["motion_std"], 0.06),
            (metrics["scene"], 0.13),
            ([1 - value for value in metrics["blur"]], 0.08),
            (metrics["exposure"], 0.08),
            (metrics["saturation"], 0.07),
            (metrics["entropy"], 0.08),
        ),
    }

    ranked: dict[HighlightMethod, tuple[HighlightCandidate, ...]] = {}
    for method in HighlightMethod:
        method_scores = _normalize(scores[method])
        ordered = sorted(
            zip(eligible, method_scores, strict=True),
            key=lambda item: (
                -item[1],
                item[0].timeline_s,
                item[0].asset_id,
                item[0].start_offset_s,
            ),
        )
        selected: list[HighlightCandidate] = []
        selected_times: list[float] = []
        for window, score in ordered:
            if any(abs(window.timeline_s - value) < min_separation_s for value in selected_times):
                continue
            rank = len(selected) + 1
            selected.append(
                HighlightCandidate(
                    method=method,
                    rank=rank,
                    asset_id=window.asset_id,
                    start_offset_s=window.start_offset_s,
                    duration_s=window.duration_s,
                    score=round(score, 6),
                    output_file_name=f"clip-{rank:02d}.mp4",
                )
            )
            selected_times.append(window.timeline_s)
            if len(selected) == top_k:
                break
        ranked[method] = tuple(selected)
    return ranked


def export_highlight_manifest(
    candidates: dict[HighlightMethod, tuple[HighlightCandidate, ...]],
    *,
    analyzed_window_count: int,
    eligible_window_count: int,
    clip_duration_s: float = DEFAULT_CLIP_DURATION_S,
) -> str:
    payload = {
        "schema_version": HIGHLIGHT_MANIFEST_SCHEMA_VERSION,
        "privacy": {
            "private_data_used": True,
            "external_data_sent": False,
            "coordinates_in_manifest": False,
            "absolute_paths_in_manifest": False,
            "recorded_timestamps_in_manifest": False,
            "visual_evidence_auto_confirmed": False,
        },
        "policy": {
            "clip_duration_s": clip_duration_s,
            "minimum_mean_speed_mps": MIN_MEAN_SPEED_MPS,
            "minimum_moving_ratio": MIN_MOVING_RATIO,
            "minimum_heading_change_degrees": MIN_HEADING_CHANGE_DEGREES,
            "minimum_visual_motion": MIN_VISUAL_MOTION,
        },
        "summary": {
            "analyzed_window_count": analyzed_window_count,
            "eligible_window_count": eligible_window_count,
            "method_count": len(candidates),
            "candidate_count": sum(len(values) for values in candidates.values()),
        },
        "methods": {
            method.value: {
                "description": METHOD_DESCRIPTIONS[method],
                "candidates": [candidate.to_dict() for candidate in values],
            }
            for method, values in candidates.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def build_highlight_clip_command(
    source_path: Path,
    output_path: Path,
    *,
    start_offset_s: float,
    duration_s: float,
    overwrite: bool,
) -> tuple[str, ...]:
    if start_offset_s < 0 or duration_s <= 0:
        raise ValueError("highlight interval must be positive")
    return (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-ss",
        str(start_offset_s),
        "-t",
        str(duration_s),
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=-2:720",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    )


def discover_and_extract_highlights(
    gpx_path: Path,
    video_root: Path,
    catalog_path: Path,
    output_directory: Path,
    *,
    clip_duration_s: float = DEFAULT_CLIP_DURATION_S,
    stride_s: float = DEFAULT_WINDOW_STRIDE_S,
    top_k: int = DEFAULT_TOP_K,
    min_separation_s: float = 30.0,
    overwrite: bool = False,
    analyzer: Callable[[Path], tuple[VideoMetricSample, ...]] = analyze_lrv_metrics,
    clip_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HighlightDiscoveryResult:
    """Analyze proxies and extract per-method comparison clips from MP4 sources."""
    if clip_duration_s <= 0 or stride_s <= 0:
        raise ValueError("clip duration and stride must be positive")
    _validate_private_output_directory(output_directory)
    manifest_path = output_directory / "highlight-comparison-manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError("highlight output already exists; choose a new directory")

    analysis = analyze_local_highlight_windows(
        gpx_path,
        video_root,
        catalog_path,
        clip_duration_s=clip_duration_s,
        stride_s=stride_s,
        analyzer=analyzer,
    )
    windows = analysis.windows
    source_paths = analysis.source_paths

    ranked = rank_highlight_windows(
        windows,
        top_k=top_k,
        min_separation_s=min_separation_s,
    )
    eligible_window_count = sum(_passes_common_interest_gate(window) for window in windows)
    if not any(ranked.values()):
        raise HighlightDiscoveryError("no windows passed the moving non-straight interest gate")

    output_directory.mkdir(parents=True, exist_ok=True)
    extracted: dict[HighlightMethod, tuple[HighlightCandidate, ...]] = {}
    for method, method_candidates in ranked.items():
        method_directory = output_directory / method.value
        method_directory.mkdir(parents=True, exist_ok=True)
        completed_candidates: list[HighlightCandidate] = []
        for candidate in method_candidates:
            source_path = source_paths.get(candidate.asset_id)
            if source_path is None or not source_path.is_file() or source_path.is_symlink():
                raise HighlightDiscoveryError("ranked local source asset is unavailable")
            output_path = method_directory / candidate.output_file_name
            if output_path.exists() and not overwrite:
                raise FileExistsError("highlight clip output already exists")
            command = build_highlight_clip_command(
                source_path,
                output_path,
                start_offset_s=candidate.start_offset_s,
                duration_s=candidate.duration_s,
                overwrite=overwrite,
            )
            try:
                process = clip_runner(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=max(60.0, candidate.duration_s * 4),
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as error:
                raise HighlightDiscoveryError("local highlight extraction could not run") from error
            if process.returncode != 0 or not output_path.is_file():
                raise HighlightDiscoveryError("local highlight extraction failed")
            completed_candidates.append(replace(candidate, output_file_name=output_path.name))
        extracted[method] = tuple(completed_candidates)

    manifest_path.write_text(
        export_highlight_manifest(
            extracted,
            analyzed_window_count=len(windows),
            eligible_window_count=eligible_window_count,
            clip_duration_s=clip_duration_s,
        ),
        encoding="utf-8",
    )
    return HighlightDiscoveryResult(
        analyzed_source_count=analysis.analyzed_source_count,
        analyzed_window_count=len(windows),
        eligible_window_count=eligible_window_count,
        extracted_clip_count=sum(len(values) for values in extracted.values()),
        candidates=extracted,
    )


def _features_for_source(
    entry: VideoCatalogEntry,
    video_to_gps_offset_s: float,
    samples: tuple[VideoMetricSample, ...],
    route_points: tuple[RoutePoint, ...],
    route_timestamps: tuple[float, ...],
    *,
    clip_duration_s: float,
    stride_s: float,
) -> tuple[WindowFeatures, ...]:
    results: list[WindowFeatures] = []
    start_offset_s = 0.0
    gps_file_start = entry.recorded_start_time + timedelta(seconds=video_to_gps_offset_s)
    while start_offset_s + clip_duration_s <= entry.duration_s:
        sample_window = tuple(
            sample
            for sample in samples
            if start_offset_s <= sample.time_s < start_offset_s + clip_duration_s
        )
        minimum_samples = max(3, math.floor(clip_duration_s * 0.6))
        if len(sample_window) >= minimum_samples:
            gps_start = gps_file_start + timedelta(seconds=start_offset_s)
            gps_end = gps_start + timedelta(seconds=clip_duration_s)
            gps = _gps_features(route_points, route_timestamps, gps_start, gps_end)
            if gps is not None:
                results.append(
                    WindowFeatures(
                        asset_id=entry.asset_id,
                        start_offset_s=start_offset_s,
                        duration_s=clip_duration_s,
                        timeline_s=gps_start.timestamp(),
                        **gps,
                        motion_mean=fmean(sample.motion for sample in sample_window),
                        motion_std=_std(sample.motion for sample in sample_window),
                        scene_change_mean=fmean(
                            sample.scene_difference for sample in sample_window
                        ),
                        scene_change_peak_ratio=(
                            sum(sample.scene_difference >= 12.0 for sample in sample_window)
                            / len(sample_window)
                        ),
                        blur_mean=fmean(sample.blur for sample in sample_window),
                        luma_mean=fmean(sample.luma for sample in sample_window),
                        dynamic_range_mean=fmean(sample.dynamic_range for sample in sample_window),
                        saturation_mean=fmean(sample.saturation for sample in sample_window),
                        entropy_mean=fmean(sample.entropy for sample in sample_window),
                    )
                )
        start_offset_s += stride_s
    return tuple(results)


def _validate_private_output_directory(output_directory: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    resolved_output = output_directory.resolve()
    try:
        relative = resolved_output.relative_to(repository_root)
    except ValueError:
        return
    if not any(
        relative == root or root in relative.parents for root in _PRIVATE_REPOSITORY_OUTPUT_ROOTS
    ):
        raise ValueError("repository highlight output must use an ignored private directory")


def _gps_features(
    points: tuple[RoutePoint, ...],
    timestamps: tuple[float, ...],
    start: datetime,
    end: datetime,
) -> dict[str, float] | None:
    left = bisect.bisect_left(timestamps, start.timestamp())
    right = bisect.bisect_right(timestamps, end.timestamp())
    selected = points[left:right]
    if len(selected) < 2:
        return None
    speeds = [point.speed_mps for point in selected if point.speed_mps is not None]
    if len(speeds) < 2:
        return None
    elevations = [point.elevation_m for point in selected if point.elevation_m is not None]
    midpoint = len(selected) // 2
    first, middle, last = selected[0], selected[midpoint], selected[-1]
    heading_change = 0.0
    if _distance_m(first, middle) >= 5 and _distance_m(middle, last) >= 5:
        heading_change = _direction_delta(
            _bearing_degrees(first, middle),
            _bearing_degrees(middle, last),
        )
    center_heading_change = 0.0
    center_span = max(1, len(selected) // 6)
    center_before = selected[max(0, midpoint - center_span)]
    center_after = selected[min(len(selected) - 1, midpoint + center_span)]
    if _distance_m(center_before, middle) >= 3 and _distance_m(middle, center_after) >= 3:
        center_heading_change = _direction_delta(
            _bearing_degrees(center_before, middle),
            _bearing_degrees(middle, center_after),
        )
    segment_distances = [
        _distance_m(segment_start, segment_end)
        for segment_start, segment_end in zip(selected, selected[1:], strict=False)
    ]
    path_distance = sum(segment_distances)
    chord_distance = _distance_m(first, last)
    bearings = [
        _bearing_degrees(segment_start, segment_end)
        for segment_start, segment_end, distance in zip(
            selected,
            selected[1:],
            segment_distances,
            strict=False,
        )
        if distance >= 3.0
    ]
    accumulated_heading_change = sum(
        _direction_delta(previous, current)
        for previous, current in zip(bearings, bearings[1:], strict=False)
    )
    ordered_speeds = sorted(speeds)
    center_speed = selected[midpoint].speed_mps
    return {
        "latitude": selected[midpoint].latitude,
        "longitude": selected[midpoint].longitude,
        "mean_speed_mps": fmean(speeds),
        "minimum_speed_mps": min(speeds),
        "speed_p10_mps": _percentile(ordered_speeds, 0.10),
        "center_speed_mps": (float(center_speed) if center_speed is not None else fmean(speeds)),
        "moving_ratio": sum(speed >= 2.5 for speed in speeds) / len(speeds),
        "heading_change_degrees": heading_change,
        "center_heading_change_degrees": center_heading_change,
        "accumulated_heading_change_degrees": accumulated_heading_change,
        "path_efficiency": (min(1.0, chord_distance / path_distance) if path_distance > 0 else 1.0),
        "speed_std_mps": _std(speeds),
        "speed_range_mps": max(speeds) - min(speeds),
        "elevation_change_m": (
            abs(elevations[-1] - elevations[0]) if len(elevations) >= 2 else 0.0
        ),
        "elevation_range_m": (max(elevations) - min(elevations) if len(elevations) >= 2 else 0.0),
    }


def _passes_common_interest_gate(window: WindowFeatures) -> bool:
    return (
        window.mean_speed_mps >= MIN_MEAN_SPEED_MPS
        and window.moving_ratio >= MIN_MOVING_RATIO
        and window.heading_change_degrees >= MIN_HEADING_CHANGE_DEGREES
        and window.motion_mean >= MIN_VISUAL_MOTION
    )


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _blend(*weighted_values: tuple[list[float], float]) -> list[float]:
    if not weighted_values:
        return []
    length = len(weighted_values[0][0])
    if any(len(values) != length for values, _weight in weighted_values):
        raise ValueError("blended score arrays must have equal lengths")
    total_weight = sum(weight for _values, weight in weighted_values)
    if total_weight <= 0:
        raise ValueError("blended score weights must be positive")
    return [
        sum(values[index] * weight for values, weight in weighted_values) / total_weight
        for index in range(length)
    ]


def _exposure_quality(window: WindowFeatures) -> float:
    midpoint_quality = max(0.0, 1.0 - abs(window.luma_mean - 128.0) / 128.0)
    range_quality = min(1.0, max(0.0, window.dynamic_range_mean / 180.0))
    return 0.7 * midpoint_quality + 0.3 * range_quality


def _recording_key(file_name: str) -> str:
    stem = Path(file_name).stem.upper()
    if len(stem) < 3 or not stem.startswith("G"):
        return stem
    return stem[2:]


# A real GoPro low-resolution proxy covers the full duration of its paired
# high-resolution chapter; a small gap only comes from encoder rounding.
_PROXY_DURATION_TOLERANCE_S = 3.0


def _proxy_matches_source_duration(proxy_path: Path, expected_duration_s: float) -> bool:
    """Reject a candidate LRV proxy whose duration does not cover its source.

    `_recording_key` pairs files by their shared numeric suffix regardless of
    the two-letter prefix (e.g. GX/GH/GL), which real-media testing on
    2026-09-02 showed is not always a valid same-recording pairing on every
    GoPro unit: an unrelated, much shorter ``.LRV`` can coincidentally share a
    chapter number with an ``.MP4`` it does not correspond to. Using such a
    mismatched proxy would silently derive metrics and extracted frames only
    from its first few seconds for any window past that point, rather than
    failing loudly. Falling back to the full-resolution source is slower but
    correct.
    """
    try:
        proxy_duration_s = probe_local_video_metadata(proxy_path).duration_s
    except VideoProbeError:
        return False
    return proxy_duration_s >= expected_duration_s - _PROXY_DURATION_TOLERANCE_S


def _std(values: Iterable[float]) -> float:
    materialized = list(values)
    return pstdev(materialized) if len(materialized) >= 2 else 0.0


def _distance_m(first: RoutePoint, second: RoutePoint) -> float:
    radius_m = 6_371_000.0
    lat_1, lat_2 = math.radians(first.latitude), math.radians(second.latitude)
    d_lat = lat_2 - lat_1
    d_lon = math.radians(second.longitude - first.longitude)
    haversine = (
        math.sin(d_lat / 2) ** 2 + math.cos(lat_1) * math.cos(lat_2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(haversine))


def _bearing_degrees(first: RoutePoint, second: RoutePoint) -> float:
    lat_1 = math.radians(first.latitude)
    lat_2 = math.radians(second.latitude)
    delta_lon = math.radians(second.longitude - first.longitude)
    x = math.sin(delta_lon) * math.cos(lat_2)
    y = math.cos(lat_1) * math.sin(lat_2) - math.sin(lat_1) * math.cos(lat_2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _direction_delta(first: float, second: float) -> float:
    return abs((second - first + 180.0) % 360.0 - 180.0)


def _percentile(ordered_values: list[float], fraction: float) -> float:
    if not ordered_values:
        raise ValueError("percentile values are required")
    if not 0 <= fraction <= 1:
        raise ValueError("percentile fraction must be between zero and one")
    position = fraction * (len(ordered_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered_values[lower]
    weight = position - lower
    return ordered_values[lower] * (1 - weight) + ordered_values[upper] * weight


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract ten local-only highlight comparison sets for human review."
    )
    parser.add_argument("gpx", type=Path)
    parser.add_argument("video_root", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clip-duration-s", type=float, default=DEFAULT_CLIP_DURATION_S)
    parser.add_argument("--stride-s", type=float, default=DEFAULT_WINDOW_STRIDE_S)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--min-separation-s", type=float, default=30.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = discover_and_extract_highlights(
        args.gpx,
        args.video_root,
        args.catalog,
        args.output,
        clip_duration_s=args.clip_duration_s,
        stride_s=args.stride_s,
        top_k=args.top_k,
        min_separation_s=args.min_separation_s,
        overwrite=args.overwrite,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
