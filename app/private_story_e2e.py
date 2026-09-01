"""Run the private, evidence-gated story E2E without external services."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.local_pipeline import LocalPipelineResult, rerun_local_director_from_package
from app.local_render import LocalRenderResult, render_local_review_film
from app.video import LocalVideoMetadata


@dataclass(frozen=True)
class PrivateStoryE2EResult:
    """Safe aggregate of a private Director rerun and silent local render."""

    director: LocalPipelineResult
    render: LocalRenderResult

    def to_dict(self) -> dict[str, object]:
        return {
            "director": self.director.to_dict(),
            "render": {
                "clip_count": self.render.clip_count,
                "duration_s": self.render.duration_s,
                "audio_included": self.render.audio_included,
                "story_order_applied": self.render.story_order_applied,
                "external_data_sent": False,
            },
            "external_data_sent": False,
        }


def run_private_story_e2e(
    package_directory: Path,
    *,
    output_file_name: str = "ride-storyteller-story-film.mp4",
    overwrite: bool = False,
    probe: Callable[[Path], LocalVideoMetadata] | None = None,
    clip_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    render_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> PrivateStoryE2EResult:
    """Create a private story film from one package with no evidence left awaiting.

    ``rerun_local_director_from_package`` first verifies the private input
    manifest and requires at least one confirmed visual-evidence decision with
    none left awaiting (per the 2026-09-01 decision, a rejected or unmatched
    event simply drops out of the story rather than blocking the rerun). The
    resulting DirectorScript is then supplied to the existing deterministic
    renderer, which rechecks both source identity and the evidence allow-list
    before invoking FFmpeg.

    This function never calls Gemini, Google Cloud, Box, or any other network
    service. It has no parameter for GPX or source-video paths, so callers
    cannot replace the reviewed journey during the final local step.
    """
    director = rerun_local_director_from_package(
        package_directory,
        probe=probe,
        clip_runner=clip_runner,
    )
    if director.director_result is None or not director.director_result.render_plan_ready:
        raise ValueError("private Director rerun did not produce a render-ready story")
    render = render_local_review_film(
        package_directory,
        output_file_name=output_file_name,
        overwrite=overwrite,
        director_script_path=package_directory / "local-director-script.json",
        runner=render_runner,
    )
    return PrivateStoryE2EResult(director=director, render=render)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render one private Ride Storyteller film with no evidence decision left awaiting."
        )
    )
    parser.add_argument("package", type=Path, help="private local pipeline package")
    parser.add_argument(
        "--output-file-name",
        default="ride-storyteller-story-film.mp4",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = run_private_story_e2e(
        args.package,
        output_file_name=args.output_file_name,
        overwrite=args.overwrite,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
