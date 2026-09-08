"""Verify one private local package is internally consistent before rendering.

This is Gate 1 of docs/completion-roadmap-ja.md: confirm that an existing
private package still refers to one journey, one confirmed clock correction,
and one source set, so the inputs of the final local E2E can be fixed.

Everything here is local and read-only. No source video, GPX, or network
service is touched: the check reads only the package's own already-written
JSON exports. The returned summary is deliberately identifier-free — counts,
durations, booleans, and fixed reason codes only, never an event ID, asset
ID, file name, path, coordinate, or timestamp — so it can be pasted into a
handoff note or an issue without leaking private material.

A package that fails any check is reported as not ready with the reason
codes that blocked it. Nothing is repaired, re-decided, or rendered here.

There are two shapes of package. The older one carries a candidate export
and an evidence review, and its questions are about settled evidence. The
newer one carries a judgement bought from the model, and the film is cut
from that -- so the export's questions do not apply to it, and it need
not have an export at all, which is exactly the shape the cloud path
produces. When a judgement is present it decides which questions are
asked; a package with neither cannot be read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analysis_record import (
    BOUGHT_ANALYSIS_PROVIDERS,
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    load_video_analysis_record,
)
from app.local_pipeline import load_local_pipeline_inputs
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    load_journey_story_plan,
)
from app.video import (
    ResolvedCandidateClip,
    VideoMatchStatus,
    evaluate_local_evidence_review,
    load_local_evidence_review,
    load_resolved_candidate_export,
    load_video_catalog,
)

PRIVATE_PACKAGE_HEALTH_SCHEMA_VERSION = "private-package-health-v1"

_INPUTS_FILE_NAME = "local-pipeline-inputs.json"
_CATALOG_FILE_NAME = "local-video-catalog.json"
_CANDIDATES_FILE_NAME = "ride-storyteller-candidates.json"
_EVIDENCE_FILE_NAME = "evidence-review.json"

# Fixed, non-identifying reason vocabulary.
REASON_CLOCK_OFFSET_MISMATCH = "clock_offset_mismatch"
REASON_EVIDENCE_AWAITING = "evidence_awaiting_present"
REASON_EVIDENCE_REJECTED = "evidence_rejected_present"
REASON_NO_CONFIRMED_EVIDENCE = "no_confirmed_evidence"
REASON_UNMATCHED_CLIPS = "timestamp_unmatched_clips"
REASON_JUDGEMENT_UNBOUGHT = "judgement_not_bought_from_a_model"
REASON_NO_JUDGED_FOOTAGE = "no_judged_footage"
# Unmatched and rejected events are reported but do not block on their own:
# per the 2026-09-01 decision they simply drop out of the story. Nor does a
# short film: the 2026-09-03 design review made the film's length follow its
# material, so a short one means the selection was too strict, which is
# information rather than a reason to refuse to render. What blocks is an
# outstanding decision, nothing confirmed, or a clock offset the package no
# longer agrees on.
BLOCKING_REASONS = frozenset(
    {
        REASON_CLOCK_OFFSET_MISMATCH,
        REASON_EVIDENCE_AWAITING,
        REASON_NO_CONFIRMED_EVIDENCE,
        REASON_JUDGEMENT_UNBOUGHT,
        REASON_NO_JUDGED_FOOTAGE,
    }
)


class PrivatePackageHealthError(RuntimeError):
    """Raised when a configured package cannot be read safely at all."""


@dataclass(frozen=True)
class PrivatePackageHealth:
    """One package's Gate 1 verdict, expressed without any private identifier."""

    is_ready: bool
    clock_offset_confirmed: bool
    candidate_clip_count: int
    matched_clip_count: int
    unmatched_clip_count: int
    confirmed_event_count: int
    awaiting_event_count: int
    rejected_event_count: int
    confirmed_duration_s: float
    film_duration_s: float
    has_story_plan: bool
    blocking_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PRIVATE_PACKAGE_HEALTH_SCHEMA_VERSION,
            "local_only": True,
            "external_data_sent": False,
            "is_ready": self.is_ready,
            "clock_offset_confirmed": self.clock_offset_confirmed,
            "counts": {
                "candidate_clips": self.candidate_clip_count,
                "matched_clips": self.matched_clip_count,
                "unmatched_clips": self.unmatched_clip_count,
                "confirmed_events": self.confirmed_event_count,
                "awaiting_events": self.awaiting_event_count,
                "rejected_events": self.rejected_event_count,
            },
            "duration": {
                "confirmed_s": round(self.confirmed_duration_s, 3),
                "film_s": round(self.film_duration_s, 3),
                "includes_chapter_cards": self.has_story_plan,
            },
            "blocking_reasons": list(self.blocking_reasons),
        }


def check_private_package_health(package_directory: Path) -> PrivatePackageHealth:
    """Read one private package and report whether it can anchor a final E2E.

    Raises `PrivatePackageHealthError` when the package cannot be read at all
    (missing directory, missing or symlinked required export). A readable but
    inconsistent package is not an error: it comes back with `is_ready=False`
    and the reason codes that blocked it.
    """
    root = _validated_root(package_directory)
    inputs = load_local_pipeline_inputs(root / _INPUTS_FILE_NAME)
    catalog = load_video_catalog(_required_file(root, _CATALOG_FILE_NAME))
    clock_offset_confirmed = catalog.video_to_gps_offset_s == inputs.video_to_gps_offset_s

    judgement = root / VIDEO_ANALYSIS_RECORD_FILE_NAME
    if judgement.is_file() and not judgement.is_symlink():
        return _judged_package_health(
            root, judgement, clock_offset_confirmed=clock_offset_confirmed
        )

    clips = load_resolved_candidate_export(_required_file(root, _CANDIDATES_FILE_NAME))
    review = load_local_evidence_review(_required_file(root, _EVIDENCE_FILE_NAME))
    result = evaluate_local_evidence_review(clips, review)

    confirmed_event_ids = set(result.confirmed_event_ids)
    confirmed_duration_s = sum(
        _clip_duration_s(clip)
        for clip in clips
        if clip.event_id in confirmed_event_ids and clip.status is VideoMatchStatus.MATCHED
    )
    # The film's own length, reported rather than judged. A plan measures the
    # whole film -- cards included -- and without one there is only footage to
    # measure.
    plan_path = root / JOURNEY_STORY_PLAN_FILE_NAME
    plan = load_journey_story_plan(plan_path) if plan_path.exists() else None
    film_duration_s = plan.total_screen_duration_s if plan is not None else confirmed_duration_s

    reasons: list[str] = []
    if not clock_offset_confirmed:
        reasons.append(REASON_CLOCK_OFFSET_MISMATCH)
    if result.awaiting_event_ids:
        reasons.append(REASON_EVIDENCE_AWAITING)
    if not confirmed_event_ids:
        reasons.append(REASON_NO_CONFIRMED_EVIDENCE)
    if result.unmatched_event_ids:
        reasons.append(REASON_UNMATCHED_CLIPS)
    if result.rejected_event_ids:
        reasons.append(REASON_EVIDENCE_REJECTED)

    is_ready = not any(reason in BLOCKING_REASONS for reason in reasons)

    return PrivatePackageHealth(
        is_ready=is_ready,
        clock_offset_confirmed=clock_offset_confirmed,
        candidate_clip_count=len(clips),
        matched_clip_count=sum(1 for clip in clips if clip.status is VideoMatchStatus.MATCHED),
        unmatched_clip_count=len(result.unmatched_event_ids),
        confirmed_event_count=len(result.confirmed_event_ids),
        awaiting_event_count=len(result.awaiting_event_ids),
        rejected_event_count=len(result.rejected_event_ids),
        confirmed_duration_s=confirmed_duration_s,
        film_duration_s=film_duration_s,
        has_story_plan=plan is not None,
        blocking_reasons=tuple(reasons),
    )


def _judged_package_health(
    root: Path, judgement: Path, *, clock_offset_confirmed: bool
) -> PrivatePackageHealth:
    """Gate 1 for a package whose film is cut from a bought judgement.

    The export's questions -- is any evidence still awaiting a decision, was
    anything rejected -- are about clips nobody will use. What can still
    block is the clock the package no longer agrees on, a judgement no
    model was paid for, and a judgement of nothing.
    """
    try:
        record = load_video_analysis_record(judgement)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PrivatePackageHealthError("private package judgement is unavailable") from error

    judged = record.analysed
    providers = {item.analysis.analysis_provider for item in judged}
    judged_duration_s = sum(
        item.analysis.end_offset_s - item.analysis.start_offset_s for item in judged
    )
    plan_path = root / JOURNEY_STORY_PLAN_FILE_NAME
    plan = load_journey_story_plan(plan_path) if plan_path.exists() else None
    film_duration_s = plan.total_screen_duration_s if plan is not None else judged_duration_s

    reasons: list[str] = []
    if not clock_offset_confirmed:
        reasons.append(REASON_CLOCK_OFFSET_MISMATCH)
    if not judged:
        reasons.append(REASON_NO_JUDGED_FOOTAGE)
    elif not providers <= BOUGHT_ANALYSIS_PROVIDERS:
        reasons.append(REASON_JUDGEMENT_UNBOUGHT)

    return PrivatePackageHealth(
        is_ready=not any(reason in BLOCKING_REASONS for reason in reasons),
        clock_offset_confirmed=clock_offset_confirmed,
        candidate_clip_count=len(judged),
        matched_clip_count=len(judged),
        unmatched_clip_count=0,
        confirmed_event_count=len(judged),
        awaiting_event_count=0,
        rejected_event_count=0,
        confirmed_duration_s=judged_duration_s,
        film_duration_s=film_duration_s,
        has_story_plan=plan is not None,
        blocking_reasons=tuple(reasons),
    )


def _validated_root(package_directory: Path) -> Path:
    if package_directory.is_symlink() or not package_directory.is_dir():
        raise PrivatePackageHealthError("private package directory is unavailable")
    return package_directory.resolve()


def _required_file(root: Path, file_name: str) -> Path:
    path = root / file_name
    if path.is_symlink() or not path.is_file():
        raise PrivatePackageHealthError("private package export is unavailable")
    return path


def _clip_duration_s(clip: ResolvedCandidateClip) -> float:
    if clip.start_offset_s is None or clip.end_offset_s is None:
        return 0.0
    return max(0.0, clip.end_offset_s - clip.start_offset_s)


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Check one private local package's Gate 1 health without reading "
            "source media or contacting any network service."
        )
    )
    parser.add_argument("package", type=Path, help="private local pipeline package")
    args = parser.parse_args()
    health = check_private_package_health(args.package)
    print(json.dumps(health.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
