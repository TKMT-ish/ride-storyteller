"""Say what judging a ride would send and cost, then do it once allowed.

This is the step that leaves the machine, so it is split in two. Planning
reads the package and reports what would be uploaded and what it would cost,
and has no side effects at all: it is the thing to put in front of a person
who is being asked to approve a spend. Running does the work, and needs both
the plan and the means -- an uploader and an analyser -- handed to it.

Neither is a default. There is no import here that could reach Google, and no
code path that uploads anything unless a caller passes something that
uploads. A module that could quietly start spending would be the wrong shape
for the decision it sits behind.

What gets sent is the small copies from `app.analysis_proxy`, never the
ride's own recordings: a candidate window is a few hundred kilobytes, and the
originals are 68.1 GiB. What comes back is written by `app.analysis_record`,
so a rerun reads the judgement rather than buying it again.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Collection
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from app.analysis_budget import (
    DEFAULT_JPY_PER_USD,
    AnalysisBudgetError,
    AnalysisStage,
    CascadePlan,
    local_stage,
    plan_cascade_within_budget,
    stills_stage,
    video_stage,
)
from app.analysis_proxy import AnalysisWindow, write_proxy_clip
from app.analysis_record import (
    VIDEO_ANALYSIS_RECORD_FILE_NAME,
    AnalysedEvent,
    VideoAnalysisRecord,
    load_video_analysis_record,
    write_video_analysis_record,
)
from app.contracts import VideoAnalysis
from app.fixed_shots import filmed_moments, fixed_shot_starts
from app.footage_candidates import (
    DEFAULT_STRIDE_S,
    DEFAULT_WINDOW_S,
    enumerate_footage_candidates,
    recording_spans,
    turn_candidates,
    windows_at,
)
from app.gopro_gps import sidecar_for
from app.gps import parse_gpx
from app.gps.moments import day_moments
from app.gps.turns import sharp_turns
from app.local_pipeline import load_local_pipeline_inputs
from app.ride_chapters import STOP_MIN_S, long_halts
from app.route_references import highway_runs, road_moments
from app.unit_economics import current_pipeline
from app.video import load_video_catalog

ANALYSIS_RUN_SCHEMA_VERSION = "analysis-run-v1"

DEFAULT_BUDGET_JPY = 500.0
# Measured across every window of two real rides, not extrapolated from a
# single clip. The first ride weighed 45.8 (95.0 MB for 2076 s of footage);
# the second, a longer day with more open road, weighed 60.6 (501.8 MB for
# 8280 s), and a plan priced at the first figure came in 32% light. The
# heavier ride is the estimate, because a quote should not be the number
# the bill beats. The first estimate here was 43.0, from one twelve-second
# sample (see app.analysis_proxy).
MEASURED_PROXY_KILOBYTES_PER_SECOND = 60.6
MEASURED_STILLS_KILOBYTES = 185.0

# Kept in the package: a rerun that must buy the judgement again should not
# also have to rebuild what it sends.
PROXY_DIRECTORY_NAME = "analysis-proxies"

# Judgements bought so far in an attempt that has not finished. Exists
# only while a run is incomplete; removed once the real record is written.
PARTIAL_RECORD_FILE_NAME = "gemini-video-analysis.partial.json"

# Judgements in flight at once. Each is one upload and one model call that
# waits on the network for most of its thirty-odd seconds, so four at a
# time is nearly four times faster and well inside the model's default
# quota. One is the sequential path, kept for tests and for caution.
DEFAULT_CONCURRENCY = 4


class AnalysisRunError(RuntimeError):
    """Raised when a ride cannot be judged as asked."""


@dataclass(frozen=True)
class AnalysisCandidate:
    """One window this run would ask about."""

    event_id: str
    asset_id: str
    start_offset_s: float
    end_offset_s: float

    @property
    def duration_s(self) -> float:
        return self.end_offset_s - self.start_offset_s


@dataclass(frozen=True)
class AnalysisRunPlan:
    """What a run would send, what it would cost, and what it would keep.

    Produced without touching the network, so it can be read and argued with
    before anyone agrees to pay for it.
    """

    candidates: tuple[AnalysisCandidate, ...]
    cascade: CascadePlan
    stills_megabytes: float
    video_megabytes: float
    already_recorded: bool

    @property
    def upload_megabytes(self) -> float:
        """Everything a full cascade would send.

        Kept apart from its two halves because they are sent by different
        stages, and comparing a measurement of one against the total reads
        as a saving when it is an overshoot.
        """
        return self.stills_megabytes + self.video_megabytes

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def watched_count(self) -> int:
        """How many candidates the paid stage is priced for."""
        return _candidates_reaching(self.cascade, "gemini-video")

    @property
    def watched_candidates(self) -> tuple[AnalysisCandidate, ...]:
        """The candidates a run may judge -- the ones this plan pays for.

        When a budget does not bind these are all of them. When it does, the
        cascade prices fewer, and a run that judged every candidate anyway
        would bill past what was approved. On one real ride a 20 yen ceiling
        prices 86 windows at 15.0 yen; judging all 173 costs 25.6.

        Which ones to keep is not arbitrary. Taking the first 86 would buy
        the first half of the journey and none of the second, because these
        are in ride order. They are spread evenly instead, so a narrowed run
        still sees the whole ride -- less densely, not less of it.
        """
        keep = self.watched_count
        if keep >= len(self.candidates):
            return self.candidates
        if keep <= 0:
            return ()
        step = len(self.candidates) / keep
        chosen = {min(len(self.candidates) - 1, int(index * step)) for index in range(keep)}
        return tuple(self.candidates[index] for index in sorted(chosen))

    def to_dict(self) -> dict[str, object]:
        """Counts, sizes and money. No event ID, asset ID, path, or file name."""
        return {
            "schema_version": ANALYSIS_RUN_SCHEMA_VERSION,
            "candidate_count": self.candidate_count,
            "watched_count": self.watched_count,
            "upload_megabytes": round(self.upload_megabytes, 1),
            "stills_megabytes": round(self.stills_megabytes, 1),
            "video_megabytes": round(self.video_megabytes, 1),
            "already_recorded": self.already_recorded,
            "cost": self.cascade.to_dict(),
            # What this ride would cost to make, against what a subscription
            # can afford (Gate 7). Linear in measured rates; see unit_economics.
            "unit_economics": current_pipeline(self.watched_count).to_dict(),
        }


ANALYSIS_SETTINGS_FILE_NAME = "analysis-settings.json"
ANALYSIS_SETTINGS_SCHEMA_VERSION = "analysis-settings-v1"


def write_analysis_settings(package_directory: Path, *, stride_s: float) -> Path:
    """Fix how this package is analysed, so plan, preflight, judge and rank agree.

    The stride decides how many windows a ride has and therefore what a
    judgement costs; a package judged at one stride must be re-planned at the
    same stride or the record and the plan describe different windows.
    """
    if stride_s <= 0:
        raise AnalysisRunError("the analysis stride must be positive")
    path = package_directory / ANALYSIS_SETTINGS_FILE_NAME
    if path.is_symlink():
        raise AnalysisRunError("the analysis settings path is unsafe")
    payload = {"schema_version": ANALYSIS_SETTINGS_SCHEMA_VERSION, "stride_s": float(stride_s)}
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def analysis_stride_s(package_directory: Path) -> float:
    """The stride this package is analysed at: what it was fixed to, else the default."""
    path = package_directory / ANALYSIS_SETTINGS_FILE_NAME
    if not path.is_file() or path.is_symlink():
        return DEFAULT_STRIDE_S
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != ANALYSIS_SETTINGS_SCHEMA_VERSION:
            raise AnalysisRunError("unsupported analysis settings schema")
        stride = float(payload["stride_s"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AnalysisRunError("the analysis settings cannot be read") from error
    if stride <= 0:
        raise AnalysisRunError("the analysis stride must be positive")
    return stride


def plan_analysis_run(
    package_directory: Path,
    *,
    budget_jpy: float = DEFAULT_BUDGET_JPY,
    jpy_per_usd: float = DEFAULT_JPY_PER_USD,
    stills_per_candidate: int = 3,
    screen_keep_ratio: float = 1.0,
    video_keep_ratio: float = 1.0,
    window_s: float = DEFAULT_WINDOW_S,
    stride_s: float | None = None,
) -> AnalysisRunPlan:
    """Work out what judging this package would involve. Sends nothing.

    Candidates come from the footage, not from where GPS raised an event.
    Measured on one real ride the difference is 7 windows against 173: the
    camera ran for over half the journey while only seven GPS events fell
    inside a recording, and taking only those threw the rest away before
    anything had judged it (see `app.footage_candidates`).

    The keep ratios default to keeping everything, because narrowing here is
    a way of fitting a budget and nothing else. Choosing which clips the film
    uses belongs to `app.gemini_selection`, once there is something to choose
    from. Conflating the two starves a small ride: seven candidates through a
    cascade tuned for two hundred leave one clip, which is not a film, and
    the budget was never the constraint. `plan_cascade_within_budget` still
    tightens these when the estimate does not fit.

    **A screening stage is planned only when it earns its place.** It exists
    to make an unaffordable job affordable: look at a few stills of every
    candidate cheaply, and watch only the survivors. Keeping everything, it
    screens nothing -- it adds its own bill and its own upload and removes
    no candidate at all. On the real ride that was 32 MB and a third of the
    quoted cost buying nothing, and it made the plan describe a run that
    `run_analysis` does not perform.

    So the direct cascade is planned first. Screening is added only when the
    direct one would have to be tightened to fit, which is exactly when
    paying for a cheap look at everything beats not looking at most of it.
    """
    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    route = parse_gpx(inputs.gpx_path)
    if stride_s is None:
        stride_s = analysis_stride_s(package_directory)
    windows = enumerate_footage_candidates(
        catalog,
        route.summary.start_time,
        route.summary.end_time,
        window_s=window_s,
        stride_s=stride_s,
    )
    # The stride misses more than half of every recording; a corner the
    # track can prove gets a window of its own where none covers it (Q1).
    windows = tuple(
        sorted(
            windows
            + turn_candidates(
                catalog,
                route.summary.start_time,
                route.summary.end_time,
                sharp_turns(route.points),
                windows,
                window_s=window_s,
            ),
            key=lambda item: (item.start_time, item.asset_id),
        )
    )
    # The moments the track proves -- setting off, each halt's two ends,
    # arriving -- get a window each where none starts there, so the film
    # can always show them (app.fixed_shots; the owner's rule, 2026-09-06).
    # The same moments the film keeps (app.route_references): the stops of
    # five minutes, joining and leaving a highway, the day's two ends.
    stops = long_halts(route.points, minimum_s=STOP_MIN_S)
    proven = filmed_moments(
        (
            *day_moments(route.points, stops),
            *road_moments(route.points, highway_runs(route.points)),
        ),
        recording_spans(catalog),
        window_s=window_s,
        points=route.points,
    )
    windows = tuple(
        sorted(
            windows
            + windows_at(
                catalog,
                route.summary.start_time,
                route.summary.end_time,
                fixed_shot_starts(proven, window_s),
                windows,
                window_s=window_s,
            ),
            key=lambda item: (item.start_time, item.asset_id),
        )
    )
    candidates = tuple(
        AnalysisCandidate(
            event_id=window.candidate_id,
            asset_id=window.asset_id,
            start_offset_s=window.start_offset_s,
            end_offset_s=window.end_offset_s,
        )
        for window in windows
    )
    if not candidates:
        raise AnalysisRunError("this package has no footage inside the ride to judge")

    seconds_each = sum(c.duration_s for c in candidates) / len(candidates)
    matched = local_stage("already-matched", keep_ratio=1.0)
    watching = video_stage(
        "gemini-video", seconds_per_candidate=seconds_each, keep_ratio=video_keep_ratio
    )
    screening = stills_stage(
        "gemini-stills",
        frames_per_candidate=stills_per_candidate,
        keep_ratio=screen_keep_ratio,
    )

    def fit(stages: tuple[AnalysisStage, ...]) -> CascadePlan:
        try:
            return plan_cascade_within_budget(
                len(candidates), stages, budget_jpy=budget_jpy, jpy_per_usd=jpy_per_usd
            )
        except AnalysisBudgetError as error:
            raise AnalysisRunError(str(error)) from error

    cascade = fit((matched, watching))
    if cascade.tightened:
        # Watching fewer candidates is the worse way to fit a budget: a cheap
        # look at all of them is what screening is for.
        cascade = fit((matched, screening, watching))

    screened = _candidates_reaching(cascade, "gemini-stills")
    watched = _candidates_reaching(cascade, "gemini-video")
    return AnalysisRunPlan(
        candidates=candidates,
        cascade=cascade,
        stills_megabytes=screened * MEASURED_STILLS_KILOBYTES / 1000,
        video_megabytes=watched * seconds_each * MEASURED_PROXY_KILOBYTES_PER_SECOND / 1000,
        already_recorded=(package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME).exists(),
    )


def _candidates_reaching(cascade: CascadePlan, stage_name: str) -> int:
    """How many candidates a named stage sees, or none if it was not planned."""
    for stage in cascade.stages:
        if stage.name == stage_name:
            return stage.candidates_in
    return 0


def run_analysis(
    package_directory: Path,
    plan: AnalysisRunPlan,
    *,
    upload: Callable[[Path, AnalysisCandidate], str],
    analyse: Callable[[str, AnalysisCandidate], VideoAnalysis],
    make_proxy: Callable[[AnalysisWindow, Path], Path] = write_proxy_clip,
    overwrite: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    refresh: Collection[str] = (),
) -> Path:
    """Judge every candidate in the plan and write the record.

    `refresh` names windows whose judgement is bought again even though
    the finished record holds one -- when the model is asked new questions
    (the photogenic score, 2026-09-07) of the windows that matter most.

    Each candidate is first copied down to something small enough to send --
    a few hundred kilobytes against a 68.1 GiB original -- and it is that
    file which is uploaded. Making the copy is local and free, so it has a
    real default; `upload` and `analyse` do not, because they leave the
    machine and one of them costs money. Nothing here can spend by being
    called.

    `upload` is handed the file and returns the URI to read it back from.
    Keeping it that simple is deliberate: an uploader that had to work out
    for itself which frames to send would be re-deciding what was already
    decided here.

    Proxies are kept in the package. A rerun that has to buy the judgement
    again should not also have to rebuild what it sends.

    Only the candidates the plan pays for are judged. When a budget binds,
    the cascade prices fewer than were enumerated, and judging the rest
    anyway would bill past what somebody approved -- 25.6 yen against a
    20 yen ceiling, on one real ride. `watched_candidates` says which, and
    spreads them across the whole journey rather than taking its first half.

    A candidate that fails is not skipped. A record missing a judgement is
    indistinguishable from one where the model saw nothing worth saying, and
    the selection would silently cut a different film.

    But a judgement that failed part-way must not throw away what was
    already paid for. Judging 173 windows is 173 billed calls made one after
    another, and a network fault at the hundred and fiftieth would otherwise
    lose a hundred and forty-nine of them and buy them all again on the next
    attempt. So each judgement is written as it arrives, and a rerun asks
    only about the windows it does not already have. The complete record is
    still written only when it is complete; the running total lives in its
    own file, which is removed once the real one exists.
    """
    if not plan.candidates:
        raise AnalysisRunError("this plan has nothing to judge")
    judging = plan.watched_candidates
    if not judging:
        raise AnalysisRunError("this plan pays for no candidate at all")
    record_path = package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
    if record_path.exists() and not overwrite:
        raise FileExistsError(
            "this package already carries a judgement; pass overwrite=True to buy it again"
        )

    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    file_names = {entry.asset_id: entry.file_name for entry in catalog.entries}
    proxy_directory = package_directory / PROXY_DIRECTORY_NAME

    partial_path = package_directory / PARTIAL_RECORD_FILE_NAME
    bought = judgements_already_bought(partial_path)
    if record_path.exists():
        # A rerun that adds windows (a turn the stride missed, say) must buy
        # only those: what the finished record already holds was paid for --
        # except the windows asked to be refreshed.
        again = set(refresh)
        for item in load_video_analysis_record(record_path).analysed:
            if item.event_id not in again:
                bought.setdefault(item.event_id, item)
    if concurrency < 1:
        raise AnalysisRunError("a run needs at least one judgement in flight")

    # Results land keyed by candidate so the record keeps the plan's order
    # whatever order the network returns them in.
    results: dict[str, AnalysedEvent] = {}
    lock = threading.Lock()

    def judge_one(candidate: AnalysisCandidate) -> None:
        file_name = file_names.get(candidate.asset_id)
        if file_name is None:
            raise AnalysisRunError("a candidate names an asset the catalog lacks")
        proxy = make_proxy(
            AnalysisWindow(
                source_path=copy_source(inputs.video_root, file_name),
                start_s=candidate.start_offset_s,
                duration_s=candidate.duration_s,
            ),
            proxy_directory / f"{candidate.event_id}.mp4",
        )
        uri = upload(proxy, candidate)
        if not uri:
            raise AnalysisRunError("a candidate was not uploaded before being judged")
        analysis = analyse(uri, candidate)
        with lock:
            results[candidate.event_id] = AnalysedEvent(
                event_id=candidate.event_id, analysis=analysis
            )
            # Written as it arrives, in plan order: this one has been paid for.
            write_video_analysis_record(
                partial_path,
                VideoAnalysisRecord(
                    tuple(results[c.event_id] for c in judging if c.event_id in results)
                ),
                overwrite=True,
            )

    for candidate in judging:
        carried = bought.get(candidate.event_id)
        if carried is not None:
            results[candidate.event_id] = carried
    todo = [c for c in judging if c.event_id not in results]

    if concurrency == 1:
        for candidate in todo:
            judge_one(candidate)
    elif todo:
        # The first fault stops new work; what is already in flight finishes
        # and is kept, because it has been paid for either way.
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(judge_one, candidate) for candidate in todo]
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for future in pending:
                future.cancel()
            for future in done:
                future.result()

    analysed = [results[c.event_id] for c in judging]

    written = write_video_analysis_record(
        record_path, VideoAnalysisRecord(tuple(analysed)), overwrite=True
    )
    partial_path.unlink(missing_ok=True)
    return written


def judgements_already_bought(partial_path: Path) -> dict[str, AnalysedEvent]:
    """What a previous attempt paid for and did not finish.

    Public because the command line reports how many a run carried rather
    than bought, which is the difference between a fault costing money
    and costing only time.

    A partial that cannot be read is an error, not an empty start. Starting
    over silently would buy every window a second time without saying so.
    """
    if not partial_path.exists():
        return {}
    try:
        record = load_video_analysis_record(partial_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AnalysisRunError(
            "this package holds an unreadable part-finished judgement; "
            "move it aside to buy the whole ride again"
        ) from error
    return {item.event_id: item for item in record.analysed}


def copy_source(video_root: Path, file_name: str) -> Path:
    """The file the small copy of a window is cut from: the camera's own proxy when it has one.

    A GoPro writes a low-resolution twin (.LRV, 768x432) beside every
    recording on the same time axis. The copy sent for judgement is smaller
    still, so cutting it from the twin loses nothing the model would see and
    spares decoding the 4K original -- which was most of the preflight's
    time (the owner's question, 2026-09-06). The film itself is still cut
    from the original; this is for the copies only.
    """
    return sidecar_for(source_recording(video_root, file_name))


def source_recording(video_root: Path, file_name: str) -> Path:
    """Find one catalogued recording under the ride's own video directory.

    Public because preflight resolves the same files to make the same
    copies; two ways of finding a ride's recording would be one too many.
    """
    if Path(file_name).name != file_name:
        raise AnalysisRunError("a catalogued recording name must not be a path")
    for candidate in video_root.rglob(file_name):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise AnalysisRunError("a catalogued recording is no longer where it was")
