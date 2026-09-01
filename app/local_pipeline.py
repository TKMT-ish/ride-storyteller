"""Run the privacy-preserving local GPX-to-review-clip preparation pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from app.agents import RuleBasedStoryPlanner, StoryOutputLanguage
from app.edit import (
    CandidateClip,
    CandidateEvidenceStatus,
    build_candidate_edit_plan,
    confirm_clip_evidence,
    review_candidate_edit_plan,
)
from app.gps import consolidate_events, extract_events, parse_gpx
from app.video import (
    LocalEvidenceReview,
    LocalReviewClip,
    LocalVideoMetadata,
    build_local_evidence_review_template,
    build_local_video_catalog,
    evaluate_local_evidence_review,
    extract_local_review_clips,
    load_local_evidence_review,
    resolve_candidate_clips,
    select_video_backed_events,
    write_candidate_exports,
    write_local_evidence_review,
    write_local_review_clip_manifest,
    write_local_video_catalog,
)

if TYPE_CHECKING:
    from app.director import GeminiDirectorTransport

LOCAL_PIPELINE_SUMMARY_SCHEMA_VERSION = "local-pipeline-summary-v1"
LOCAL_PIPELINE_INPUT_MANIFEST_SCHEMA_VERSION = "local-pipeline-input-manifest-v1"
_PRIVATE_REPOSITORY_OUTPUT_ROOTS = (
    Path("private-media"),
    Path("data/private"),
    Path("media/private"),
)
_DERIVED_PRIVATE_MEDIA_ROOT = Path("private-media/work")


@dataclass(frozen=True)
class LocalPipelineResult:
    route_point_count: int
    route_duration_s: float
    route_distance_m: float
    event_count: int
    chapter_count: int
    catalog_entry_count: int
    catalog_issue_count: int
    matched_clip_count: int
    unmatched_clip_count: int
    review_clip_count: int
    candidate_plan_ready_for_edit: bool
    director_result: object = None  # DirectorPipelineResult | None
    director_script_view: dict[str, object] | None = None
    next_gate: str = "human_visual_evidence_review"

    def to_dict(self) -> dict[str, object]:
        from app.director_pipeline import DirectorPipelineResult
        payload: dict[str, object] = {
            "schema_version": LOCAL_PIPELINE_SUMMARY_SCHEMA_VERSION,
            "privacy": {
                "private_data_used": True,
                "external_data_sent": False,
                "coordinates_in_summary": False,
                "absolute_paths_in_summary": False,
                "visual_evidence_auto_confirmed": False,
            },
            "route": {
                "point_count": self.route_point_count,
                "duration_s": self.route_duration_s,
                "distance_m": self.route_distance_m,
            },
            "counts": {
                "events": self.event_count,
                "chapters": self.chapter_count,
                "catalog_entries": self.catalog_entry_count,
                "catalog_issues": self.catalog_issue_count,
                "matched_clips": self.matched_clip_count,
                "unmatched_clips": self.unmatched_clip_count,
                "review_clips": self.review_clip_count,
            },
            "candidate_plan_ready_for_edit": self.candidate_plan_ready_for_edit,
            "next_gate": self.next_gate,
        }
        if isinstance(self.director_result, DirectorPipelineResult):
            director_payload = self.director_result.to_dict()
            if self.director_script_view is not None:
                director_payload["director_script"] = self.director_script_view
            payload["director"] = director_payload
        return payload


@dataclass(frozen=True)
class LocalPipelineInputs:
    """Private source identity required to rerun a reviewed local package."""

    gpx_path: Path
    video_root: Path
    video_to_gps_offset_s: float
    target_duration_s: float
    output_language: StoryOutputLanguage

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_PIPELINE_INPUT_MANIFEST_SCHEMA_VERSION,
            "gpx_path": str(self.gpx_path),
            "video_root": str(self.video_root),
            "video_to_gps_offset_s": self.video_to_gps_offset_s,
            "target_duration_s": self.target_duration_s,
            "output_language": self.output_language.value,
        }


def prepare_local_review_package(
    gpx_path: Path,
    video_root: Path,
    output_directory: Path,
    *,
    video_to_gps_offset_s: float,
    clock_offset_confirmed: bool,
    target_duration_s: float = 300.0,
    output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    extract_reviews: bool = True,
    overwrite: bool = False,
    probe: Callable[[Path], LocalVideoMetadata] | None = None,
    clip_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    director_mode: bool = False,
    gemini_transport: GeminiDirectorTransport | None = None,
    allow_external_director: bool = False,
) -> LocalPipelineResult:
    """Prepare private catalogs, candidate exports, and optional review proxies.

    Pass ``director_mode=True`` to additionally run the Scout → Director →
    ScriptExecutor pipeline after the standard preparation steps.  When
    ``director_mode=False`` (the default), the function behaves exactly as
    before and no Director-related code is executed.

    No Google, Gemini, Box, map, or other network client is imported or called
    in the default path. In director mode, Gemini is only called if
    ``gemini_transport`` is supplied, confirmed events are available, and
    ``allow_external_director=True`` is explicitly set.

    ``overwrite=True`` regenerates derived catalogs and review proxies, but it
    never replaces an existing ``evidence-review.json``. Human visual-evidence
    decisions are a separate gate and must be deliberately edited through the
    evidence-review workflow. A review that no longer matches the regenerated
    candidate event set raises ``ValueError`` rather than being silently reset.
    """
    _validate_private_output_directory(output_directory)
    _validate_source_video_directory(video_root)
    expected_outputs = (
        output_directory / "local-pipeline-inputs.json",
        output_directory / "local-video-catalog.json",
        output_directory / "ride-storyteller-candidates.json",
        output_directory / "ride-storyteller-candidates.csv",
        output_directory / "local-pipeline-summary.json",
        output_directory / "evidence-review.json",
        output_directory / "review-clip-manifest.json",
    )
    if not overwrite and any(path.exists() for path in expected_outputs):
        raise FileExistsError(
            "local pipeline output already exists; choose a new directory or pass overwrite=True"
        )
    inputs_path = output_directory / "local-pipeline-inputs.json"
    inputs = LocalPipelineInputs(
        gpx_path=gpx_path.resolve(),
        video_root=video_root.resolve(),
        video_to_gps_offset_s=video_to_gps_offset_s,
        target_duration_s=target_duration_s,
        output_language=StoryOutputLanguage(output_language),
    )
    if inputs_path.exists() and load_local_pipeline_inputs(inputs_path) != inputs:
        raise ValueError("private local pipeline inputs do not match the existing package")

    if probe is None:
        catalog_build = build_local_video_catalog(
            video_root,
            video_to_gps_offset_s=video_to_gps_offset_s,
            clock_offset_confirmed=clock_offset_confirmed,
        )
    else:
        catalog_build = build_local_video_catalog(
            video_root,
            video_to_gps_offset_s=video_to_gps_offset_s,
            clock_offset_confirmed=clock_offset_confirmed,
            probe=probe,
        )

    route = parse_gpx(gpx_path)
    events = consolidate_events(extract_events(route, asset_name_hint="local_catalog"))
    video_backed_events = select_video_backed_events(
        events,
        catalog_build.catalog,
        target_duration_s=target_duration_s,
    )
    if not video_backed_events:
        raise ValueError("no GPS events have local timestamp-matched video coverage")
    story_plan = RuleBasedStoryPlanner().plan_selected_events(
        route.summary,
        video_backed_events,
        target_duration_s=target_duration_s,
        output_language=output_language,
    )
    candidate_plan = build_candidate_edit_plan(story_plan, events)
    resolved_clips = resolve_candidate_clips(candidate_plan, events, catalog_build.catalog)
    matched_clips = tuple(clip for clip in resolved_clips if clip.status.value == "matched")

    output_directory.mkdir(parents=True, exist_ok=True)
    _write_or_validate_local_pipeline_inputs(inputs_path, inputs)
    write_local_video_catalog(
        output_directory / "local-video-catalog.json",
        catalog_build,
        overwrite=overwrite,
    )
    write_candidate_exports(output_directory, resolved_clips)
    evidence_review_path = output_directory / "evidence-review.json"
    if not evidence_review_path.exists():
        write_local_evidence_review(
            evidence_review_path,
            build_local_evidence_review_template(resolved_clips),
        )
    evidence_review = load_local_evidence_review(evidence_review_path)
    review_eval = evaluate_local_evidence_review(resolved_clips, evidence_review)
    reviewed_candidate_clips = _apply_evidence_review_to_candidate_clips(
        candidate_plan.clips,
        evidence_review,
    )
    candidate_review = review_candidate_edit_plan(
        replace(candidate_plan, clips=reviewed_candidate_clips)
    )

    review_clips: tuple[LocalReviewClip, ...] = ()
    if extract_reviews and matched_clips:
        review_clips = extract_local_review_clips(
            matched_clips,
            video_root=video_root,
            output_directory=output_directory / "review-clips",
            overwrite=overwrite,
            runner=clip_runner,
        )
    write_local_review_clip_manifest(
        output_directory / "review-clip-manifest.json",
        review_clips,
        overwrite=overwrite,
    )

    # ------------------------------------------------------------------
    # Optional Director pipeline (opt-in via director_mode=True)
    # ------------------------------------------------------------------
    director_result = None
    director_script_view = None
    if director_mode:
        from app.director import browser_safe_script_view
        from app.director_pipeline import run_director_pipeline

        if review_eval.confirmed_event_ids:
            director_result, _plan, script = run_director_pipeline(
                events,
                resolved_clips,
                reviewed_candidate_clips,
                review_eval,
                gemini_transport=gemini_transport,
                allow_external_director=allow_external_director,
                output_directory=output_directory,
            )
            director_script_view = browser_safe_script_view(
                script,
                fallback_used=director_result.fallback_used,
            )

    result = LocalPipelineResult(
        route_point_count=route.summary.point_count,
        route_duration_s=route.summary.duration_s,
        route_distance_m=route.summary.total_distance_m,
        event_count=len(events),
        chapter_count=len(story_plan.chapters),
        catalog_entry_count=len(catalog_build.catalog.entries),
        catalog_issue_count=len(catalog_build.issues),
        matched_clip_count=len(matched_clips),
        unmatched_clip_count=len(resolved_clips) - len(matched_clips),
        review_clip_count=len(review_clips),
        candidate_plan_ready_for_edit=candidate_review.is_ready_for_edit,
        director_result=director_result,
        director_script_view=director_script_view,
        next_gate=_next_local_pipeline_gate(candidate_review, director_result),
    )
    (output_directory / "local-pipeline-summary.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def rerun_local_director_from_package(
    output_directory: Path,
    *,
    probe: Callable[[Path], LocalVideoMetadata] | None = None,
    clip_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LocalPipelineResult:
    """Rerun the offline Director from the exact private inputs of one package.

    The private input manifest prevents an automation from guessing source
    folders or silently pairing human evidence decisions with a different ride.
    """
    inputs = load_local_pipeline_inputs(output_directory / "local-pipeline-inputs.json")
    return prepare_local_review_package(
        inputs.gpx_path,
        inputs.video_root,
        output_directory,
        video_to_gps_offset_s=inputs.video_to_gps_offset_s,
        clock_offset_confirmed=True,
        target_duration_s=inputs.target_duration_s,
        output_language=inputs.output_language,
        overwrite=True,
        probe=probe,
        clip_runner=clip_runner,
        director_mode=True,
    )


def load_local_pipeline_inputs(path: Path) -> LocalPipelineInputs:
    """Load exact private source inputs, failing closed on malformed or moved files."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("private local pipeline inputs are unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("private local pipeline inputs are unreadable") from error
    expected_keys = {
        "schema_version",
        "gpx_path",
        "video_root",
        "video_to_gps_offset_s",
        "target_duration_s",
        "output_language",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("private local pipeline inputs have an invalid schema")
    if payload["schema_version"] != LOCAL_PIPELINE_INPUT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("private local pipeline inputs have an invalid schema")
    gpx_path = _private_input_path(payload["gpx_path"], "GPX", expect_directory=False)
    video_root = _private_input_path(
        payload["video_root"], "video directory", expect_directory=True
    )
    offset = _private_input_number(payload["video_to_gps_offset_s"], "clock offset")
    target_duration = _private_input_number(payload["target_duration_s"], "target duration")
    try:
        output_language = StoryOutputLanguage(payload["output_language"])
    except (TypeError, ValueError) as error:
        raise ValueError("private local pipeline inputs have an invalid language") from error
    return LocalPipelineInputs(
        gpx_path=gpx_path,
        video_root=video_root,
        video_to_gps_offset_s=offset,
        target_duration_s=target_duration,
        output_language=output_language,
    )


def _write_or_validate_local_pipeline_inputs(
    path: Path, inputs: LocalPipelineInputs
) -> None:
    if path.exists():
        if load_local_pipeline_inputs(path) != inputs:
            raise ValueError("private local pipeline inputs do not match the existing package")
        return
    payload = json.dumps(inputs.to_dict(), ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")


def _private_input_path(value: object, label: str, *, expect_directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"private local pipeline inputs have an invalid {label}")
    path = Path(value)
    if path.is_symlink() or (not path.is_dir() if expect_directory else not path.is_file()):
        raise ValueError(f"private local pipeline {label} is unavailable")
    return path.resolve()


def _private_input_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"private local pipeline inputs have an invalid {label}")
    return float(value)


def _apply_evidence_review_to_candidate_clips(
    candidate_clips: tuple[CandidateClip, ...],
    review: LocalEvidenceReview,
) -> tuple[CandidateClip, ...]:
    """Apply a validated local review to fresh candidate clips, fail closed.

    ``CandidateClip`` carries evidence status into the Scout layer, while the
    persisted local review records the human decision. This bridge makes the
    decision explicit without treating the review allow-list as sufficient
    evidence on its own. It accepts only fresh awaiting clips, so a caller
    cannot silently replace an already-decided status.
    """
    decisions = {decision.event_id: decision for decision in review.decisions}
    candidate_event_ids = tuple(clip.event_id for clip in candidate_clips)
    if set(candidate_event_ids) != set(decisions):
        raise ValueError(
            "evidence review must contain exactly one decision per candidate clip"
        )

    reviewed_clips: list[CandidateClip] = []
    for clip in candidate_clips:
        if clip.evidence_status is not CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE:
            raise ValueError("only fresh awaiting candidate clips may receive a review")
        decision = decisions[clip.event_id]
        if decision.evidence_status is CandidateEvidenceStatus.AWAITING_VIDEO_EVIDENCE:
            reviewed_clips.append(clip)
            continue
        source = decision.evidence_source
        if source is None:
            raise ValueError("decided evidence review requires a source")
        reviewed_clips.append(
            confirm_clip_evidence(
                clip,
                confirmed=decision.evidence_status is CandidateEvidenceStatus.CONFIRMED,
                source=source,
            )
        )
    return tuple(reviewed_clips)


def _next_local_pipeline_gate(
    candidate_review: object,
    director_result: object,
) -> str:
    """Return the next local-only action without overstating render readiness."""
    from app.director_pipeline import DirectorPipelineResult
    from app.edit import CandidateEditReview

    if not isinstance(candidate_review, CandidateEditReview):
        raise TypeError("candidate_review must be CandidateEditReview")
    if candidate_review.rejected_event_ids:
        return "replace_rejected_candidate_clips"
    if candidate_review.event_ids_requiring_evidence:
        return "human_visual_evidence_review"
    if candidate_review.missing_duration_s > 0:
        return "add_timestamp_matched_candidates"
    if not candidate_review.is_ready_for_edit:
        return "human_visual_evidence_review"
    if isinstance(director_result, DirectorPipelineResult):
        return "render_director_script"
    return "run_offline_director"


def _validate_private_output_directory(output_directory: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    resolved_output = output_directory.resolve()
    try:
        relative = resolved_output.relative_to(repository_root)
    except ValueError:
        return
    is_private_output = any(
        relative == root or root in relative.parents
        for root in _PRIVATE_REPOSITORY_OUTPUT_ROOTS
    )
    if not is_private_output:
        raise ValueError(
            "output inside the repository must be under an ignored private-media directory"
        )


def _validate_source_video_directory(video_root: Path) -> None:
    """Reject private derived media as source footage for the final story path."""
    repository_root = Path(__file__).resolve().parents[1]
    try:
        relative = video_root.resolve().relative_to(repository_root)
    except ValueError:
        return
    if relative == _DERIVED_PRIVATE_MEDIA_ROOT or _DERIVED_PRIVATE_MEDIA_ROOT in relative.parents:
        raise ValueError(
            "source video directory must not be inside private-media/work derived output"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a local-only GPX-to-review-clip package without external calls."
    )
    parser.add_argument("gpx", type=Path, nargs="?", help="private Garmin GPX file")
    parser.add_argument("video_root", type=Path, nargs="?", help="private local video directory")
    parser.add_argument("--output", type=Path, help="private output directory")
    parser.add_argument(
        "--resume-output",
        type=Path,
        help="rerun the offline Director from one private output package's saved inputs",
    )
    parser.add_argument("--clock-offset-s", type=float)
    parser.add_argument("--clock-offset-confirmed", action="store_true")
    parser.add_argument("--target-duration-s", type=float, default=300.0)
    parser.add_argument(
        "--language",
        choices=tuple(language.value for language in StoryOutputLanguage),
        default=StoryOutputLanguage.JAPANESE.value,
    )
    parser.add_argument("--skip-review-clips", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--director-mode",
        action="store_true",
        help=(
            "run the offline RuleBased Director for confirmed evidence only; "
            "does not call Gemini or other external services"
        ),
    )
    args = parser.parse_args()
    if args.resume_output is not None:
        if args.gpx is not None or args.video_root is not None or args.output is not None:
            parser.error("--resume-output cannot be combined with GPX, video_root, or --output")
        result = rerun_local_director_from_package(args.resume_output)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    if args.gpx is None or args.video_root is None or args.output is None:
        parser.error("GPX, video_root, and --output are required unless --resume-output is used")
    if args.clock_offset_s is None:
        parser.error("--clock-offset-s is required unless --resume-output is used")
    result = prepare_local_review_package(
        args.gpx,
        args.video_root,
        args.output,
        video_to_gps_offset_s=args.clock_offset_s,
        clock_offset_confirmed=args.clock_offset_confirmed,
        target_duration_s=args.target_duration_s,
        output_language=StoryOutputLanguage(args.language),
        extract_reviews=not args.skip_review_clips,
        overwrite=args.overwrite,
        director_mode=args.director_mode,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
