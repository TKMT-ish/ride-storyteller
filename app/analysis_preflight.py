"""Make everything a run would send, locally, and measure it -- before paying.

The plan a person is asked to approve says 121.3 MB and 27.9 yen, and both
are arithmetic: measured constants multiplied by a candidate count. Nothing
had ever cut all of a real ride's windows down to size. A window whose
recording ends earlier than the catalogue believes, a file FFmpeg cannot
seek, a source that has moved -- none of those are visible until something
tries, and the first thing that tries should not be a run that is spending.

So this does the whole local half: every proxy, from the ride's own files,
with nothing uploaded and nothing judged. What comes back is what a run
would actually send, in bytes that were counted rather than estimated.

The copies are left where a run will look for them, so preflighting is not
wasted work: the run that follows finds them made. Only what the run will
send is made -- when a budget binds, the plan pays for fewer windows than
were enumerated, and encoding the rest would be minutes spent on files
nobody uploads.

**This fails open, and the run fails closed.** They want opposite things. A
run that skipped a failing candidate would write a record missing a
judgement, indistinguishable from one the model had nothing to say about,
and would silently cut a different film -- so it stops. Preflight exists to
find out how much is wrong, and stopping at the first fault answers a
question nobody asked. It tries every window and reports what failed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.analysis_proxy import AnalysisWindow, write_proxy_clip
from app.analysis_run import (
    PROXY_DIRECTORY_NAME,
    AnalysisCandidate,
    AnalysisRunError,
    AnalysisRunPlan,
    copy_source,
)
from app.local_pipeline import load_local_pipeline_inputs
from app.video import load_video_catalog

ANALYSIS_PREFLIGHT_SCHEMA_VERSION = "analysis-preflight-v1"

# Fixed, non-identifying: a failure names what went wrong, never which ride.
REASON_UNKNOWN_ASSET = "unknown_asset"
REASON_SOURCE_MISSING = "source_missing"
REASON_COPY_FAILED = "copy_failed"
REASON_COPY_EMPTY = "copy_empty"


@dataclass(frozen=True)
class PreflightFailure:
    """One window that could not be prepared, named by reason alone."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("a preflight failure needs a reason code")


@dataclass(frozen=True)
class PreflightResult:
    """What a run would send, counted rather than estimated."""

    candidate_count: int
    prepared_count: int
    measured_megabytes: float
    estimated_megabytes: float
    estimated_total_megabytes: float
    largest_megabytes: float
    failures: tuple[PreflightFailure, ...]

    @property
    def ready(self) -> bool:
        """Every window a run would send can actually be made."""
        return not self.failures and self.prepared_count == self.candidate_count

    @property
    def measured_share_of_estimate(self) -> float:
        """Measured against the estimate for the same thing.

        Not against the total a full cascade would send: preflight makes the
        clips, and a screening stage's stills are a separate third of that
        total. Measuring one and dividing by both turns a 6% overshoot into
        an apparent 22% saving, which is how this was first misread.
        """
        if self.estimated_megabytes <= 0:
            return 0.0
        return self.measured_megabytes / self.estimated_megabytes

    def to_dict(self) -> dict[str, object]:
        """Counts, sizes, and reason codes. No path, file name, or identifier."""
        reasons: dict[str, int] = {}
        for failure in self.failures:
            reasons[failure.reason] = reasons.get(failure.reason, 0) + 1
        return {
            "schema_version": ANALYSIS_PREFLIGHT_SCHEMA_VERSION,
            "candidate_count": self.candidate_count,
            "prepared_count": self.prepared_count,
            "measured_megabytes": round(self.measured_megabytes, 1),
            "estimated_megabytes": round(self.estimated_megabytes, 1),
            "estimated_total_megabytes": round(self.estimated_total_megabytes, 1),
            "measured_share_of_estimate": round(self.measured_share_of_estimate, 3),
            "largest_megabytes": round(self.largest_megabytes, 2),
            "ready": self.ready,
            "failures": reasons,
        }


def run_preflight(
    package_directory: Path,
    plan: AnalysisRunPlan,
    *,
    make_proxy: Callable[[AnalysisWindow, Path], Path] = write_proxy_clip,
    rebuild: bool = False,
) -> PreflightResult:
    """Cut every candidate down to size locally. Uploads nothing, judges nothing.

    There is no uploader and no analyser to pass, and no import here reaches
    Google. That is the point: this is the part of a run that can be done in
    full without anyone approving a spend, so it should be impossible to
    spend by running it.

    A copy that already exists is measured rather than remade, unless
    `rebuild` says otherwise. Re-encoding a ride's worth of windows to learn
    what is already on disk is a waste of several minutes.
    """
    preparing = plan.watched_candidates
    if not preparing:
        raise AnalysisRunError("this plan has nothing to prepare")

    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    file_names = {entry.asset_id: entry.file_name for entry in catalog.entries}
    proxy_directory = package_directory / PROXY_DIRECTORY_NAME

    prepared = 0
    total_bytes = 0
    largest_bytes = 0
    failures: list[PreflightFailure] = []

    for candidate in preparing:
        made = _prepare_one(
            candidate,
            file_names=file_names,
            video_root=inputs.video_root,
            destination=proxy_directory / f"{candidate.event_id}.mp4",
            make_proxy=make_proxy,
            rebuild=rebuild,
            failures=failures,
        )
        if made is None:
            continue
        size = made.stat().st_size
        prepared += 1
        total_bytes += size
        largest_bytes = max(largest_bytes, size)

    return PreflightResult(
        candidate_count=len(preparing),
        prepared_count=prepared,
        measured_megabytes=total_bytes / 1_000_000,
        # The clips, which is what was made here -- not the whole cascade.
        estimated_megabytes=plan.video_megabytes,
        estimated_total_megabytes=plan.upload_megabytes,
        largest_megabytes=largest_bytes / 1_000_000,
        failures=tuple(failures),
    )


def _prepare_one(
    candidate: AnalysisCandidate,
    *,
    file_names: dict[str, str],
    video_root: Path,
    destination: Path,
    make_proxy: Callable[[AnalysisWindow, Path], Path],
    rebuild: bool,
    failures: list[PreflightFailure],
) -> Path | None:
    """One window's copy, or None with a reason recorded."""
    file_name = file_names.get(candidate.asset_id)
    if file_name is None:
        failures.append(PreflightFailure(REASON_UNKNOWN_ASSET))
        return None
    if destination.is_file() and not rebuild and destination.stat().st_size > 0:
        return destination
    try:
        source = copy_source(video_root, file_name)
    except AnalysisRunError:
        failures.append(PreflightFailure(REASON_SOURCE_MISSING))
        return None
    try:
        made = make_proxy(
            AnalysisWindow(
                source_path=source,
                start_s=candidate.start_offset_s,
                duration_s=candidate.duration_s,
            ),
            destination,
        )
    except Exception:
        # Which window failed is the ride's business; that one did is ours.
        failures.append(PreflightFailure(REASON_COPY_FAILED))
        return None
    if not made.is_file() or made.stat().st_size == 0:
        failures.append(PreflightFailure(REASON_COPY_EMPTY))
        return None
    return made
