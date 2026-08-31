"""Create local review proxies for timestamp-matched candidate clips."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from .catalog import ResolvedCandidateClip, VideoMatchStatus
from .inventory import build_local_video_inventory
from .local_catalog import SOURCE_VIDEO_SUFFIXES

LOCAL_REVIEW_CLIP_MANIFEST_SCHEMA_VERSION = "local-review-clip-manifest-v1"


class LocalClipExtractionError(RuntimeError):
    """Raised when FFmpeg cannot create a local review proxy safely."""


@dataclass(frozen=True)
class LocalReviewClip:
    event_id: str
    asset_id: str
    output_file_name: str
    duration_s: float

    def __post_init__(self) -> None:
        if not self.event_id or not self.asset_id:
            raise ValueError("review clip event and asset IDs are required")
        _safe_file_name(self.output_file_name)
        if self.duration_s <= 0:
            raise ValueError("review clip duration must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "asset_id": self.asset_id,
            "output_file_name": self.output_file_name,
            "duration_s": self.duration_s,
        }


def export_local_review_clip_manifest(clips: tuple[LocalReviewClip, ...]) -> str:
    return json.dumps(
        {
            "schema_version": LOCAL_REVIEW_CLIP_MANIFEST_SCHEMA_VERSION,
            "clips": [clip.to_dict() for clip in clips],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def load_local_review_clip_manifest(path: Path) -> tuple[LocalReviewClip, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != LOCAL_REVIEW_CLIP_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported local review clip manifest schema")
    clips = tuple(
        LocalReviewClip(
            event_id=item["event_id"],
            asset_id=item["asset_id"],
            output_file_name=item["output_file_name"],
            duration_s=float(item["duration_s"]),
        )
        for item in payload.get("clips", [])
    )
    event_ids = [clip.event_id for clip in clips]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("review clip manifest event IDs must be unique")
    return clips


def write_local_review_clip_manifest(
    output_path: Path,
    clips: tuple[LocalReviewClip, ...],
    *,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "review manifest already exists; choose a new path or pass overwrite=True"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(export_local_review_clip_manifest(clips), encoding="utf-8")
    return output_path


def extract_local_review_clips(
    clips: tuple[ResolvedCandidateClip, ...],
    *,
    video_root: Path,
    output_directory: Path,
    overwrite: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[LocalReviewClip, ...]:
    """Transcode matched source intervals into private 720p review clips.

    The command runs without a shell and never contacts a network service. Source
    paths are recovered from deterministic inventory asset IDs and are never
    included in returned records or raised error messages.
    """
    if not clips:
        raise ValueError("at least one resolved candidate clip is required")
    if any(clip.status is not VideoMatchStatus.MATCHED for clip in clips):
        raise ValueError("all review clips must be timestamp matched")
    event_ids = [clip.event_id for clip in clips]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("review clip event IDs must be unique")

    inventory = build_local_video_inventory(video_root)
    resolved_root = video_root.resolve()
    source_paths = {
        entry.asset_id: resolved_root.joinpath(*entry.relative_path.split("/"))
        for entry in inventory.entries
        if entry.extension in SOURCE_VIDEO_SUFFIXES
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    results: list[LocalReviewClip] = []

    for index, clip in enumerate(clips, start=1):
        if clip.asset_id is None or clip.start_offset_s is None or clip.end_offset_s is None:
            raise ValueError("matched review clip must include asset ID and offsets")
        duration_s = clip.end_offset_s - clip.start_offset_s
        if duration_s <= 0:
            raise ValueError("matched review clip duration must be positive")
        source_path = source_paths.get(clip.asset_id)
        if source_path is None or not source_path.is_file() or source_path.is_symlink():
            raise LocalClipExtractionError("matched local source asset is unavailable")

        output_file_name = f"review-{index:03d}.mp4"
        output_path = output_directory / output_file_name
        if output_path.exists() and not overwrite:
            raise FileExistsError(
                "review output already exists; choose a new directory or pass overwrite=True"
            )
        command = _review_clip_command(
            source_path,
            output_path,
            start_offset_s=clip.start_offset_s,
            duration_s=duration_s,
            overwrite=overwrite,
        )
        try:
            completed = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(60.0, duration_s * 4),
            )
        except FileNotFoundError as error:
            raise LocalClipExtractionError(
                "ffmpeg is required for local clip extraction"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise LocalClipExtractionError("local clip extraction timed out") from error
        if completed.returncode != 0:
            raise LocalClipExtractionError("ffmpeg could not create a local review clip")
        if not output_path.is_file():
            raise LocalClipExtractionError("ffmpeg did not create the expected review clip")
        results.append(
            LocalReviewClip(
                event_id=clip.event_id,
                asset_id=clip.asset_id,
                output_file_name=output_file_name,
                duration_s=duration_s,
            )
        )
    return tuple(results)


def _review_clip_command(
    source_path: Path,
    output_path: Path,
    *,
    start_offset_s: float,
    duration_s: float,
    overwrite: bool,
) -> tuple[str, ...]:
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


def _safe_file_name(value: str) -> None:
    if (
        not value
        or "\x00" in value
        or PurePosixPath(value).name != value
        or PureWindowsPath(value).name != value
        or value in {".", ".."}
    ):
        raise ValueError("review clip manifest accepts file names only")
