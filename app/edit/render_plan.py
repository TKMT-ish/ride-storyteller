"""Create a safe, inspectable FFmpeg plan after evidence confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.video.catalog import ResolvedCandidateClip


class RenderPlanStatus(StrEnum):
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    READY_FOR_FFMPEG = "ready_for_ffmpeg"


@dataclass(frozen=True)
class FfmpegRenderPlan:
    status: RenderPlanStatus
    output_file_name: str
    command: tuple[str, ...] | None
    reasons: tuple[str, ...]
    clip_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "output_file_name": self.output_file_name,
            "command": list(self.command) if self.command else None,
            "reasons": list(self.reasons),
            "clip_count": self.clip_count,
        }


def build_ffmpeg_render_plan(
    clips: tuple[ResolvedCandidateClip, ...],
    *,
    visual_evidence_confirmed_event_ids: tuple[str, ...] = (),
    output_file_name: str = "ride-storyteller-film.mp4",
) -> FfmpegRenderPlan:
    """Fail closed until timestamp matches and visual evidence are both confirmed."""
    _safe_file_name(output_file_name)
    confirmed = set(visual_evidence_confirmed_event_ids)
    reasons: list[str] = []
    if not clips:
        reasons.append("レンダリングする候補クリップがありません。")
    unmatched = [clip.event_id for clip in clips if clip.status.value != "matched"]
    if unmatched:
        reasons.append("GPS時刻と対応しない候補クリップがあります。")
    unconfirmed = [clip.event_id for clip in clips if clip.event_id not in confirmed]
    if unconfirmed:
        reasons.append("映像証拠の確認が完了していない候補クリップがあります。")
    if reasons:
        return FfmpegRenderPlan(
            status=RenderPlanStatus.NEEDS_HUMAN_REVIEW,
            output_file_name=output_file_name,
            command=None,
            reasons=tuple(reasons),
            clip_count=len(clips),
        )

    command = _ffmpeg_command(clips, output_file_name)
    return FfmpegRenderPlan(
        status=RenderPlanStatus.READY_FOR_FFMPEG,
        output_file_name=output_file_name,
        command=command,
        reasons=(),
        clip_count=len(clips),
    )


def _ffmpeg_command(
    clips: tuple[ResolvedCandidateClip, ...], output_file_name: str
) -> tuple[str, ...]:
    command: list[str] = ["ffmpeg", "-y"]
    filters: list[str] = []
    for index, clip in enumerate(clips):
        if clip.file_name is None or clip.start_offset_s is None or clip.end_offset_s is None:
            raise ValueError("matched clip must include file name and offsets")
        _safe_file_name(clip.file_name)
        duration_s = clip.end_offset_s - clip.start_offset_s
        if duration_s <= 0:
            raise ValueError("matched clip duration must be positive")
        command.extend(
            ("-ss", str(clip.start_offset_s), "-t", str(duration_s), "-i", clip.file_name)
        )
        filters.append(f"[{index}:v][{index}:a]")
    command.extend(
        (
            "-filter_complex",
            "".join(filters) + f"concat=n={len(clips)}:v=1:a=1[v][a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            output_file_name,
        )
    )
    return tuple(command)


def _safe_file_name(value: str) -> None:
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or "\x00" in value
        or posix_path.name != value
        or windows_path.name != value
        or value in {".", ".."}
    ):
        raise ValueError("FFmpeg plan accepts file names only, not paths")
