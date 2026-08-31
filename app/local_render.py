"""Render confirmed local review clips into a silent private draft film."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from app.video import (
    evaluate_local_evidence_review,
    load_local_evidence_review,
    load_local_review_clip_manifest,
    load_resolved_candidate_export,
)


class LocalRenderBlockedError(RuntimeError):
    """Raised when an evidence or file gate prevents local rendering."""


@dataclass(frozen=True)
class LocalRenderResult:
    output_file_name: str
    clip_count: int
    duration_s: float
    audio_included: bool = False
    story_order_applied: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "output_file_name": self.output_file_name,
            "clip_count": self.clip_count,
            "duration_s": self.duration_s,
            "audio_included": self.audio_included,
            "story_order_applied": self.story_order_applied,
            "external_data_sent": False,
        }


def render_local_review_film(
    package_directory: Path,
    *,
    output_file_name: str = "ride-storyteller-review-film.mp4",
    overwrite: bool = False,
    director_script_path: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LocalRenderResult:
    """Render confirmed review clips, optionally in DirectorScript story order."""
    _safe_file_name(output_file_name)
    clips = load_resolved_candidate_export(
        package_directory / "ride-storyteller-candidates.json"
    )
    review = load_local_evidence_review(package_directory / "evidence-review.json")
    review_result = evaluate_local_evidence_review(clips, review)
    if not review_result.ready_for_render:
        raise LocalRenderBlockedError(
            "local render is blocked: " + ", ".join(review_result.reasons)
        )

    review_clips = load_local_review_clip_manifest(
        package_directory / "review-clip-manifest.json"
    )
    review_by_event = {clip.event_id: clip for clip in review_clips}
    ordered_clips = clips
    story_order_applied = director_script_path is not None
    if director_script_path is not None:
        from app.director_pipeline import load_private_director_script_artifact
        from app.edit.render_plan import RenderPlanStatus
        from app.executor import ScriptExecutor

        if director_script_path.parent.resolve() != package_directory.resolve():
            raise LocalRenderBlockedError(
                "DirectorScript must be stored in the same private render package"
            )
        script = load_private_director_script_artifact(director_script_path)
        if any(scene.transition_type != "cut" for scene in script.scenes):
            raise LocalRenderBlockedError(
                "local render cannot execute a non-cut DirectorScript transition"
            )
        plan = ScriptExecutor().execute(
            script,
            clips,
            visual_evidence_confirmed_event_ids=review_result.confirmed_event_ids,
        )
        if plan.status is not RenderPlanStatus.READY_FOR_FFMPEG:
            raise LocalRenderBlockedError(
                "DirectorScript does not satisfy the local render evidence gate"
            )
        clips_by_event = {clip.event_id: clip for clip in clips}
        ordered_clips = tuple(
            clips_by_event[scene_clip.event_id]
            for scene in script.scenes
            for scene_clip in scene.clips
        )

    ordered_reviews = []
    for clip in ordered_clips:
        review_clip = review_by_event.get(clip.event_id)
        if review_clip is None or review_clip.asset_id != clip.asset_id:
            raise LocalRenderBlockedError("confirmed review clip manifest is incomplete")
        ordered_reviews.append(review_clip)
    if len(review_by_event) != len(ordered_reviews):
        raise LocalRenderBlockedError("review clip manifest contains unexpected events")

    review_directory = package_directory / "review-clips"
    input_paths: list[Path] = []
    for review_clip in ordered_reviews:
        path = review_directory / review_clip.output_file_name
        if not path.is_file() or path.is_symlink():
            raise LocalRenderBlockedError("a confirmed local review clip is unavailable")
        input_paths.append(path)

    output_path = package_directory / output_file_name
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "render output already exists; choose a new name or pass overwrite=True"
        )
    command = _render_command(input_paths, output_path, overwrite=overwrite)
    total_duration_s = sum(clip.duration_s for clip in ordered_reviews)
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(120.0, total_duration_s * 5),
        )
    except FileNotFoundError as error:
        raise LocalRenderBlockedError("ffmpeg is required for local rendering") from error
    except subprocess.TimeoutExpired as error:
        raise LocalRenderBlockedError("local rendering timed out") from error
    if completed.returncode != 0:
        raise LocalRenderBlockedError("ffmpeg could not render the local review film")
    if not output_path.is_file():
        raise LocalRenderBlockedError("ffmpeg did not create the expected local film")
    return LocalRenderResult(
        output_file_name=output_file_name,
        clip_count=len(ordered_reviews),
        duration_s=total_duration_s,
        story_order_applied=story_order_applied,
    )


def _render_command(
    input_paths: list[Path], output_path: Path, *, overwrite: bool
) -> tuple[str, ...]:
    command: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
    ]
    for path in input_paths:
        command.extend(("-i", str(path)))
    video_inputs = "".join(f"[{index}:v:0]" for index in range(len(input_paths)))
    command.extend(
        (
            "-filter_complex",
            f"{video_inputs}concat=n={len(input_paths)}:v=1:a=0[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(output_path),
        )
    )
    return tuple(command)


def _safe_file_name(value: str) -> None:
    if (
        not value
        or "\x00" in value
        or PurePosixPath(value).name != value
        or PureWindowsPath(value).name != value
        or value in {".", ".."}
    ):
        raise ValueError("local render accepts an output file name only")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a silent local film from human-confirmed review clips."
    )
    parser.add_argument("package", type=Path, help="private local pipeline package")
    parser.add_argument(
        "--output-file-name",
        default="ride-storyteller-review-film.mp4",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--director-script",
        type=Path,
        help="private local-director-script.json to apply its story order",
    )
    args = parser.parse_args()
    result = render_local_review_film(
        args.package,
        output_file_name=args.output_file_name,
        overwrite=args.overwrite,
        director_script_path=args.director_script,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
