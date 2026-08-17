"""Read one local video file's container metadata with an explicit ffprobe call.

Unlike the directory inventory, this module opens a video file's container
headers locally to read technical metadata. It never uploads the file, decodes
frames, or creates a GPS-matching catalog automatically.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .inventory import SUPPORTED_VIDEO_SUFFIXES


class VideoProbeError(RuntimeError):
    """Raised when local technical metadata cannot be read safely."""


@dataclass(frozen=True)
class LocalVideoMetadata:
    """Technical metadata for one local video file, not visual evidence."""

    file_name: str
    duration_s: float
    recorded_start_time: datetime | None
    video_codec: str | None
    width: int | None
    height: int | None
    frames_per_second: float | None
    has_audio: bool

    def __post_init__(self) -> None:
        if not self.file_name:
            raise ValueError("file_name is required")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if self.recorded_start_time and self.recorded_start_time.tzinfo is None:
            raise ValueError("recorded_start_time must be timezone-aware when present")
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be both present or both absent")
        if self.width is not None and (self.width <= 0 or self.height is None or self.height <= 0):
            raise ValueError("width and height must be positive")
        if self.frames_per_second is not None and self.frames_per_second <= 0:
            raise ValueError("frames_per_second must be positive when present")

    def to_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "duration_s": self.duration_s,
            "recorded_start_time": _isoformat_utc(self.recorded_start_time)
            if self.recorded_start_time
            else None,
            "video_codec": self.video_codec,
            "width": self.width,
            "height": self.height,
            "frames_per_second": self.frames_per_second,
            "has_audio": self.has_audio,
        }


def probe_local_video_metadata(
    path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LocalVideoMetadata:
    """Read technical metadata from one supported local file using ``ffprobe``.

    The command is invoked without a shell and receives the path as one
    argument. It runs locally only; callers must separately validate camera
    clock accuracy before using the result in a video catalog.
    """
    if not path.is_file():
        raise ValueError("video path must be an existing file")
    if path.is_symlink():
        raise ValueError("video path must not be a symlink")
    if path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise ValueError("video path must have a supported video suffix")

    command = (
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:format_tags=creation_time:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    )
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise VideoProbeError("ffprobe is required for local video metadata probing") from error
    except subprocess.TimeoutExpired as error:
        raise VideoProbeError("local video metadata probing timed out") from error

    if completed.returncode != 0:
        raise VideoProbeError("ffprobe could not read local video metadata")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise VideoProbeError("ffprobe returned invalid metadata") from error
    return _metadata_from_ffprobe_payload(path.name, payload)


def export_local_video_metadata(metadata: LocalVideoMetadata) -> str:
    """Serialize metadata for an explicit private output file."""
    return json.dumps(
        {"schema_version": "local-video-metadata-v1", "metadata": metadata.to_dict()},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def write_local_video_metadata(
    output_path: Path, metadata: LocalVideoMetadata, *, overwrite: bool = False
) -> Path:
    """Write a metadata record only to a caller-selected private path."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "metadata output already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(export_local_video_metadata(metadata), encoding="utf-8")
    return output_path


def _metadata_from_ffprobe_payload(file_name: str, payload: dict[str, Any]) -> LocalVideoMetadata:
    format_payload = _as_dict(payload.get("format"))
    duration_s = _positive_float(format_payload.get("duration"), "video duration")
    tags = _as_dict(format_payload.get("tags"))
    streams = [_as_dict(value) for value in _as_list(payload.get("streams"))]
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        {},
    )
    width = _optional_positive_int(video_stream.get("width"))
    height = _optional_positive_int(video_stream.get("height"))
    if (width is None) != (height is None):
        raise VideoProbeError("ffprobe returned incomplete video dimensions")
    return LocalVideoMetadata(
        file_name=file_name,
        duration_s=duration_s,
        recorded_start_time=_parse_aware_time(tags.get("creation_time")),
        video_codec=_optional_string(video_stream.get("codec_name")),
        width=width,
        height=height,
        frames_per_second=_parse_frame_rate(video_stream.get("avg_frame_rate")),
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _positive_float(value: object, label: str) -> float:
    try:
        result = float(str(value))
    except (TypeError, ValueError) as error:
        raise VideoProbeError(f"ffprobe did not return a valid {label}") from error
    if result <= 0:
        raise VideoProbeError(f"ffprobe did not return a valid {label}")
    return result


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        result = int(str(value))
    except (TypeError, ValueError) as error:
        raise VideoProbeError("ffprobe returned invalid video dimensions") from error
    if result <= 0:
        raise VideoProbeError("ffprobe returned invalid video dimensions")
    return result


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or value in {"", "0/0", "N/A"}:
        return None
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        result = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise VideoProbeError("ffprobe returned an invalid frame rate") from error
    if result <= 0:
        raise VideoProbeError("ffprobe returned an invalid frame rate")
    return result


def _parse_aware_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise VideoProbeError("ffprobe returned an invalid creation time") from error
    if result.tzinfo is None:
        raise VideoProbeError("ffprobe creation time must include a timezone")
    return result.astimezone(UTC)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read one local video's technical metadata with ffprobe; no upload occurs."
    )
    parser.add_argument("video", type=Path, help="one private MP4, MOV, or LRV file")
    parser.add_argument("--output", type=Path, required=True, help="private JSON output path")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    args = parser.parse_args()

    metadata = probe_local_video_metadata(args.video)
    write_local_video_metadata(args.output, metadata, overwrite=args.overwrite)
    print("Created local-only technical metadata record.")


if __name__ == "__main__":
    main()
