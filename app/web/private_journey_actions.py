"""The three things a person can start from the console, and the one gate.

The console reads. This is what it may set going: making the copies to send
(local, free, minutes), buying the judgement (uploads, bills), and cutting
the film (local, free, minutes). Each runs once at a time in a background
thread, and the console polls for where it has got to.

The gate is the point. Buying a judgement is the one action here that
spends money, and approving it is not a checkbox: the request has to carry
the figure the console showed, to the yen, and the bucket the copies go to.
A figure that does not match is refused before anything is imported that
could reach Google, so a stale page or a mistyped amount starts no upload.
The number a person approves is the number they were shown.

What a job reports back is browser-safe by construction: a kind, a state,
a fixed reason code, and counts. A failure never carries its message --
messages carry paths -- only that it failed, and why in one word.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.analysis_cli import (
    AnalysisCommandError,
    CloudSignInExpired,
    command_judge,
    command_preflight,
)
from app.analysis_run import DEFAULT_BUDGET_JPY, AnalysisRunError
from app.private_journey_film import PrivateJourneyFilmError, run_private_journey_film
from app.web.private_journey_intake import (
    IntakeRefused,
    IntakeRoots,
    check_package_name,
    check_sources,
    create_package,
)

JOB_PREFLIGHT = "preflight"
JOB_JUDGE = "judge"
JOB_FILM = "film"
JOB_INTAKE = "intake"
JOB_KINDS = frozenset({JOB_PREFLIGHT, JOB_JUDGE, JOB_FILM, JOB_INTAKE})

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"

# Fixed, non-identifying: why a request was refused or a job failed.
REASON_ANOTHER_JOB_RUNNING = "another_job_is_running"
REASON_APPROVAL_MISMATCH = "approval_does_not_match_the_figure"
REASON_BUCKET_REQUIRED = "bucket_required"
REASON_UNKNOWN_TRACK = "unknown_music_track"
REASON_UNKNOWN_JOB = "unknown_job"
REASON_JUDGEMENT_ALREADY_BOUGHT = "judgement_already_bought"
REASON_PACKAGE_REFUSED = "package_refused_the_request"
REASON_JOB_FAILED = "job_failed"
# Told apart from a package that refused the request, because it is not
# about this ride at all and there is one thing to do about it.
REASON_CLOUD_SIGN_IN_EXPIRED = "cloud_sign_in_expired"

# The library on this machine; the page offers these and the server checks
# a request against the same list, so an arbitrary string never reaches
# the file system as a track name.
MUSIC_TRACK_IDS: tuple[str, ...] = (
    "wholesome",
    "enchanted-valley",
    "windswept",
    "rising-tide",
    "lightless-dawn",
)
# No music is a choice, and the default one: the owner called the library
# terrible, riders on the forums want the engine, and the research puts
# music in intros and montages at most. A track is added on request.
NO_MUSIC_TRACK_ID = "none"
DEFAULT_MUSIC_TRACK_ID = NO_MUSIC_TRACK_ID
DEFAULT_MUSIC_DIRECTORY = Path("private-media/music")

Runner = Callable[[Callable[[], None]], None]


def run_in_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


def run_inline(target: Callable[[], None]) -> None:
    """For tests: the job runs to completion before `start` returns."""
    target()


class JobRefused(RuntimeError):
    """A request the console must answer with a reason, not start."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class JobState:
    """Where one job has got to, in terms safe to show."""

    kind: str
    state: str
    reason: str | None = None
    started_at: float = 0.0
    finished_at: float | None = None
    result: dict[str, object] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.state == STATE_RUNNING

    def to_dict(self) -> dict[str, object]:
        elapsed = (self.finished_at if self.finished_at is not None else time.monotonic()) - (
            self.started_at
        )
        return {
            "kind": self.kind,
            "state": self.state,
            "reason": self.reason,
            "elapsed_s": round(max(0.0, elapsed), 1),
            "result": dict(self.result),
        }


_IDLE = JobState(kind="", state=STATE_IDLE)


def approve_judgement(
    figure_jpy: float, *, approve_jpy: object, bucket: object
) -> tuple[float, str]:
    """The gate: the figure shown, to the yen, and somewhere to send to.

    Returns the accepted figure and bucket, or raises with a fixed reason.
    Checked before anything else, and before any import that could reach
    Google, so nothing about this can begin an upload.
    """
    try:
        offered = round(float(approve_jpy), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise JobRefused(REASON_APPROVAL_MISMATCH) from None
    if offered != round(figure_jpy, 2):
        raise JobRefused(REASON_APPROVAL_MISMATCH)
    name = str(bucket or "").strip()
    if not name:
        raise JobRefused(REASON_BUCKET_REQUIRED)
    return offered, name


def check_music_track(track_id: object) -> str:
    name = str(track_id or DEFAULT_MUSIC_TRACK_ID).strip()
    if name != NO_MUSIC_TRACK_ID and name not in MUSIC_TRACK_IDS:
        raise JobRefused(REASON_UNKNOWN_TRACK)
    return name


class PrivateJourneyJobs:
    """One job at a time, for one process; the console polls its state."""

    def __init__(self, *, runner: Runner = run_in_thread) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._current: JobState = _IDLE

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._current.to_dict()

    @property
    def current(self) -> JobState:
        with self._lock:
            return self._current

    def _begin(self, kind: str) -> None:
        with self._lock:
            if self._current.is_running:
                raise JobRefused(REASON_ANOTHER_JOB_RUNNING)
            self._current = JobState(kind=kind, state=STATE_RUNNING, started_at=time.monotonic())

    def _finish(
        self, *, result: dict[str, object] | None = None, reason: str | None = None
    ) -> None:
        with self._lock:
            self._current = replace(
                self._current,
                state=STATE_FAILED if reason else STATE_DONE,
                reason=reason,
                finished_at=time.monotonic(),
                result=result or {},
            )

    def _run(self, kind: str, work: Callable[[], dict[str, object]]) -> JobState:
        self._begin(kind)

        def target() -> None:
            try:
                result = work()
            except FileExistsError:
                self._finish(reason=REASON_JUDGEMENT_ALREADY_BOUGHT)
            except (JobRefused, IntakeRefused) as refused:
                # Its reason is one of the fixed codes, safe to show.
                self._finish(reason=refused.reason)
            except CloudSignInExpired:
                self._finish(reason=REASON_CLOUD_SIGN_IN_EXPIRED)
            except (AnalysisCommandError, AnalysisRunError, PrivateJourneyFilmError):
                self._finish(reason=REASON_PACKAGE_REFUSED)
            except Exception:
                # The message may name a path; that it failed is all a page needs.
                self._finish(reason=REASON_JOB_FAILED)
            else:
                self._finish(result=result)

        self._runner(target)
        return self.current

    # --- the three jobs -------------------------------------------------------

    def start_preflight(self, package: Path, *, budget_jpy: float = DEFAULT_BUDGET_JPY) -> JobState:
        """Make every copy a run would send. Local and free."""

        def work() -> dict[str, object]:
            payload = command_preflight(package, budget_jpy=budget_jpy, rebuild=False)
            preflight = payload["preflight"]
            assert isinstance(preflight, dict)
            return {
                "prepared_count": preflight["prepared_count"],
                "candidate_count": preflight["candidate_count"],
                "measured_megabytes": preflight["measured_megabytes"],
                "ready": preflight["ready"],
            }

        return self._run(JOB_PREFLIGHT, work)

    def start_judge(
        self,
        package: Path,
        *,
        figure_jpy: float,
        approve_jpy: object,
        bucket: object,
        budget_jpy: float = DEFAULT_BUDGET_JPY,
    ) -> JobState:
        """Buy the judgement. Refused unless the figure shown was approved."""
        _, bucket_name = approve_judgement(figure_jpy, approve_jpy=approve_jpy, bucket=bucket)

        def work() -> dict[str, object]:
            payload = command_judge(
                package,
                budget_jpy=budget_jpy,
                bucket=bucket_name,
                prefix="",
                approved=True,
                overwrite=False,
            )
            return {
                "newly_bought": payload["newly_bought"],
                "carried_from_earlier_attempt": payload["carried_from_earlier_attempt"],
            }

        return self._run(JOB_JUDGE, work)

    def start_film(
        self,
        package: Path,
        *,
        music_track_id: object = DEFAULT_MUSIC_TRACK_ID,
        music_directory: Path = DEFAULT_MUSIC_DIRECTORY,
    ) -> JobState:
        """Cut the film, silent unless a track was chosen. Local and free."""
        track = check_music_track(music_track_id)
        scored = track != NO_MUSIC_TRACK_ID

        def work() -> dict[str, object]:
            run_private_journey_film(
                package,
                overwrite=True,
                music_track_id=track if scored else None,
                music_directory=music_directory,
            )
            return {"scored": scored}

        return self._run(JOB_FILM, work)

    def start_intake(
        self,
        roots: IntakeRoots,
        *,
        gpx: object,
        video_root: object,
        name: object,
        offset_s: object,
        target_duration_s: object = 300.0,
        on_created: Callable[[Path], None] | None = None,
    ) -> JobState:
        """Build a new day's package. The cheap refusals come before the job.

        The offset is confirmed inside the job, against a proposal recomputed
        there, so what is agreed to is what the evidence says now.
        """
        check_sources(roots, gpx=gpx, video_root=video_root)
        check_package_name(roots, name)

        def work() -> dict[str, object]:
            created = create_package(
                roots,
                gpx=gpx,
                video_root=video_root,
                name=name,
                offset_s=offset_s,
                target_duration_s=target_duration_s,
            )
            if on_created is not None:
                on_created(created)
            return {"package": created.name}

        return self._run(JOB_INTAKE, work)
