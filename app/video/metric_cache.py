"""Cache local-only video metrics without retaining source identifiers.

The highlight research workflow may need to tune gates repeatedly over large private
recordings. This cache persists only derived numeric samples, under the caller's
private output directory. Cache entries deliberately contain neither source paths,
file names, timestamps, coordinates, nor visual frames.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from .gpmf_metrics import GpmfMetricSample
from .highlight_discovery import VideoMetricSample

PRIVATE_METRIC_CACHE_SCHEMA_VERSION = "private-local-metric-cache-v1"
_FINGERPRINT_BYTES = 32 * 1024
_VIDEO_METRIC_KIND = "video-metrics"
_GPMF_METRIC_KIND = "gpmf-metrics"


class PrivateMetricCache:
    """Persist derived local metrics below one already-private output directory.

    The caller owns the boundary check for ``directory``. The research runner
    passes a child of its validated private output directory; this class never
    writes beside a source video and never sends data to another process.
    """

    def __init__(self, directory: Path) -> None:
        if directory.exists() and directory.is_symlink():
            raise ValueError("private metric cache directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory

    def load_or_analyze_video_metrics(
        self,
        source_path: Path,
        analyzer: Callable[[Path], tuple[VideoMetricSample, ...]],
    ) -> tuple[VideoMetricSample, ...]:
        """Return cached FFmpeg metrics or calculate and persist them locally."""
        cached = self._load(_VIDEO_METRIC_KIND, source_path)
        if cached is not None:
            try:
                return tuple(_video_sample_from_dict(item) for item in cached)
            except (KeyError, TypeError, ValueError):
                pass

        samples = analyzer(source_path)
        self._write(
            _VIDEO_METRIC_KIND,
            source_path,
            tuple(_video_sample_to_dict(sample) for sample in samples),
        )
        return samples

    def load_or_analyze_gpmf_metrics(
        self,
        source_path: Path,
        analyzer: Callable[[Path], tuple[GpmfMetricSample, ...]],
    ) -> tuple[GpmfMetricSample, ...]:
        """Return cached local GPMF metrics or calculate and persist them locally."""
        cached = self._load(_GPMF_METRIC_KIND, source_path)
        if cached is not None:
            try:
                return tuple(_gpmf_sample_from_dict(item) for item in cached)
            except (KeyError, TypeError, ValueError):
                pass

        samples = analyzer(source_path)
        self._write(
            _GPMF_METRIC_KIND,
            source_path,
            tuple(_gpmf_sample_to_dict(sample) for sample in samples),
        )
        return samples

    def _load(
        self,
        metric_kind: str,
        source_path: Path,
    ) -> tuple[Mapping[str, object], ...] | None:
        cache_path = self._cache_path(metric_kind, source_path)
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != PRIVATE_METRIC_CACHE_SCHEMA_VERSION
                or payload.get("metric_kind") != metric_kind
                or not isinstance(payload.get("samples"), list)
                or not all(isinstance(item, dict) for item in payload["samples"])
            ):
                return None
            return tuple(payload["samples"])
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return None

    def _write(
        self,
        metric_kind: str,
        source_path: Path,
        samples: tuple[dict[str, float], ...],
    ) -> None:
        cache_path = self._cache_path(metric_kind, source_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": PRIVATE_METRIC_CACHE_SCHEMA_VERSION,
            "metric_kind": metric_kind,
            "samples": samples,
        }
        temporary_path = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary_path.replace(cache_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _cache_path(self, metric_kind: str, source_path: Path) -> Path:
        return self._directory / metric_kind / f"{_source_fingerprint(source_path)}.json"


def _source_fingerprint(source_path: Path) -> str:
    """Hash a bounded local fingerprint without storing an input identifier."""
    if not source_path.is_file() or source_path.is_symlink():
        raise ValueError("metric cache input must be an existing non-symlink file")
    with source_path.open("rb") as stream:
        start = stream.read(_FINGERPRINT_BYTES)
        size = stream.seek(0, 2)
        stream.seek(max(0, size - _FINGERPRINT_BYTES))
        end = stream.read(_FINGERPRINT_BYTES)
    stat = source_path.stat()
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    digest.update(b":")
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    digest.update(b":")
    digest.update(start)
    digest.update(b":")
    digest.update(end)
    return digest.hexdigest()


def _video_sample_to_dict(sample: VideoMetricSample) -> dict[str, float]:
    return {
        "time_s": sample.time_s,
        "motion": sample.motion,
        "scene_difference": sample.scene_difference,
        "blur": sample.blur,
        "luma": sample.luma,
        "dynamic_range": sample.dynamic_range,
        "saturation": sample.saturation,
        "entropy": sample.entropy,
    }


def _video_sample_from_dict(data: Mapping[str, object]) -> VideoMetricSample:
    return VideoMetricSample(
        time_s=_number(data, "time_s"),
        motion=_number(data, "motion"),
        scene_difference=_number(data, "scene_difference"),
        blur=_number(data, "blur"),
        luma=_number(data, "luma"),
        dynamic_range=_number(data, "dynamic_range"),
        saturation=_number(data, "saturation"),
        entropy=_number(data, "entropy"),
    )


def _gpmf_sample_to_dict(sample: GpmfMetricSample) -> dict[str, float]:
    return {
        "time_s": sample.time_s,
        "duration_s": sample.duration_s,
        "gyro_sustained_rad_s": sample.gyro_sustained_rad_s,
        "gyro_jitter_rad_s": sample.gyro_jitter_rad_s,
        "gyro_peak_rad_s": sample.gyro_peak_rad_s,
        "acceleration_jitter_mps2": sample.acceleration_jitter_mps2,
        "iso_mean": sample.iso_mean,
        "shutter_mean_s": sample.shutter_mean_s,
        "luma_mean": sample.luma_mean,
        "uniformity_mean": sample.uniformity_mean,
        "natural_scene_probability": sample.natural_scene_probability,
        "built_scene_probability": sample.built_scene_probability,
        "scene_confidence": sample.scene_confidence,
        "hue_weight_mean": sample.hue_weight_mean,
    }


def _gpmf_sample_from_dict(data: Mapping[str, object]) -> GpmfMetricSample:
    return GpmfMetricSample(
        time_s=_number(data, "time_s"),
        duration_s=_number(data, "duration_s"),
        gyro_sustained_rad_s=_number(data, "gyro_sustained_rad_s"),
        gyro_jitter_rad_s=_number(data, "gyro_jitter_rad_s"),
        gyro_peak_rad_s=_number(data, "gyro_peak_rad_s"),
        acceleration_jitter_mps2=_number(data, "acceleration_jitter_mps2"),
        iso_mean=_number(data, "iso_mean"),
        shutter_mean_s=_number(data, "shutter_mean_s"),
        luma_mean=_number(data, "luma_mean"),
        uniformity_mean=_number(data, "uniformity_mean"),
        natural_scene_probability=_number(data, "natural_scene_probability"),
        built_scene_probability=_number(data, "built_scene_probability"),
        scene_confidence=_number(data, "scene_confidence"),
        hue_weight_mean=_number(data, "hue_weight_mean"),
    )


def _number(data: Mapping[str, object], name: str) -> float:
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"cached {name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"cached {name} must be a finite number")
    return number
