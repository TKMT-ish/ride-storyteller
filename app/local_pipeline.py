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
_PRIVATE_REPOSITORY_OUTPUT_ROOTS = (
    Path("private-media"),
    Path("data/private"),
    Path("media/private"),
)


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
    expected_outputs = (
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a local-only GPX-to-review-clip package without external calls."
    )
    parser.add_argument("gpx", type=Path, help="private Garmin GPX file")
    parser.add_argument("video_root", type=Path, help="private local video directory")
    parser.add_argument("--output", type=Path, required=True, help="private output directory")
    parser.add_argument("--clock-offset-s", type=float, required=True)
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
