"""The judged path as stages a browser can show, in front of the film's.

`PrivateJourneyStatus` shows a ride from checked inputs to a scored film,
and knows nothing of what now decides the film: the windows drawn from the
footage, the small copies made of them, and the judgement bought from the
model. Those three stages come first here, and the existing ones follow,
so one page reads from "what would this cost" to "watch the film".

Everything in the payload is browser-safe by construction -- counts, sizes,
money, and fixed reason codes. No path, file name, window identifier, or
model text leaves the package. The one thing a viewer needs to decide about
*this ride* is whether to spend, and for that they need the figure and
nothing else -- but a spend sends footage of strangers who agreed to
nothing, and deciding that honestly also needs to know what is sent, to
whom, and for how long it is kept. That part is the same for every ride, so
it travels as one fixed block (`app.data_handling_disclosure`) rather than
recomputed stage by stage.

Reading is free. Planning opens no video; the copies and the judgement are
only reported on, never made or bought, by anything in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME, load_video_analysis_record
from app.analysis_run import (
    PARTIAL_RECORD_FILE_NAME,
    PROXY_DIRECTORY_NAME,
    AnalysisRunError,
    AnalysisRunPlan,
    plan_analysis_run,
)
from app.data_handling_disclosure import data_handling_disclosure
from app.private_journey_film import BOUGHT_ANALYSIS_PROVIDERS
from app.web.private_journey_status import (
    PrivateJourneyStatus,
    PrivateJourneyStatusError,
)

PRIVATE_JOURNEY_CONSOLE_SCHEMA_VERSION = "private-journey-console-v1"

STAGE_FOOTAGE_PLANNED = "footage_planned"
STAGE_COPIES_PREPARED = "copies_prepared"
STAGE_FOOTAGE_JUDGED = "footage_judged"
# Stands in for the film's own stages when its status cannot be read.
STAGE_FILM_STATUS = "film_status"

STATE_DONE = "done"
STATE_PENDING = "pending"
STATE_BLOCKED = "blocked"
STATE_IN_PROGRESS = "in_progress"

ACTION_RESOLVE_BLOCKING = "resolve_blocking_reasons"
ACTION_PREPARE_COPIES = "prepare_the_copies"
ACTION_APPROVE_AND_JUDGE = "approve_and_judge"
ACTION_WAIT_FOR_JUDGEMENT = "wait_for_the_judgement"
ACTION_MAKE_FILM = "make_the_film"
ACTION_CHOOSE_MUSIC = "choose_music"
ACTION_WATCH_FILM = "watch_the_film"

# Fixed, non-identifying: why the judged path cannot go on.
REASON_NO_FOOTAGE_IN_RIDE = "no_footage_inside_the_ride"
REASON_OVER_BUDGET = "no_cascade_fits_the_budget"
REASON_PACKAGE_UNREADABLE = "package_cannot_be_read"
REASON_JUDGEMENT_UNBOUGHT = "judgement_not_bought_from_a_model"
REASON_JUDGEMENT_UNREADABLE = "judgement_cannot_be_read"
REASON_FILM_STATUS_UNAVAILABLE = "film_status_unavailable"


class PrivateJourneyConsoleError(RuntimeError):
    """Raised when the console cannot describe this package."""


@dataclass(frozen=True)
class PrivateJourneyConsole:
    """One package, read from footage windows through to the scored film."""

    status: PrivateJourneyStatus

    @classmethod
    def from_environment(cls) -> "PrivateJourneyConsole":
        try:
            return cls(status=PrivateJourneyStatus.from_environment())
        except PrivateJourneyStatusError as error:
            raise PrivateJourneyConsoleError(str(error)) from error

    @classmethod
    def from_directory(cls, package_directory: Path) -> "PrivateJourneyConsole":
        try:
            return cls(status=PrivateJourneyStatus.from_directory(package_directory))
        except PrivateJourneyStatusError as error:
            raise PrivateJourneyConsoleError(str(error)) from error

    @property
    def package_directory(self) -> Path:
        return self.status.package_directory

    def payload(self) -> dict[str, object]:
        """Every stage, judged path first, with only browser-safe facts.

        The film's own status still measures a package against the older
        candidate export, which a package judged from its footage never has
        -- the same shape the cloud path produces. That must not hide the
        judged path: when the film's status cannot be read, its stages are
        replaced by one blocked marker and the judged path is shown in full.
        """
        planned, plan = self._footage_planned_stage()
        prepared = self._copies_prepared_stage(plan)
        judged = self._footage_judged_stage(plan)

        try:
            film = self.status.payload()
        except PrivateJourneyStatusError:
            # Before a judgement exists there is simply no film to report on
            # yet; that is "not yet", not "blocked". Once one exists and the
            # film's status still cannot be read, something is wrong.
            unjudged = judged["state"] in (STATE_PENDING, STATE_IN_PROGRESS)
            film = {
                "stages": [
                    {"key": STAGE_FILM_STATUS, "state": STATE_PENDING}
                    if unjudged
                    else {
                        "key": STAGE_FILM_STATUS,
                        "state": STATE_BLOCKED,
                        "blocking_reasons": [REASON_FILM_STATUS_UNAVAILABLE],
                    }
                ],
                "chapters": [],
                "next_action": ACTION_MAKE_FILM,
            }

        stages = [planned, prepared, judged, *film["stages"]]
        return {
            "schema_version": PRIVATE_JOURNEY_CONSOLE_SCHEMA_VERSION,
            "local_only": True,
            "external_data_sent": False,
            "stages": stages,
            "chapters": film["chapters"],
            "next_action": _next_action(stages, str(film["next_action"])),
            # What approving the judgement stage would send, to whom, and for
            # how long it is kept -- fixed facts, the same for every package.
            "data_handling": data_handling_disclosure(),
        }

    # --- the three stages the film's own status does not know about -----------

    def _footage_planned_stage(self) -> tuple[dict[str, object], AnalysisRunPlan | None]:
        """What judging would send and cost. Computed here, sends nothing."""
        try:
            plan = plan_analysis_run(self.package_directory)
        except AnalysisRunError as error:
            reason = _plan_failure_reason(str(error))
            return (
                {
                    "key": STAGE_FOOTAGE_PLANNED,
                    "state": STATE_BLOCKED,
                    "blocking_reasons": [reason],
                },
                None,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return (
                {
                    "key": STAGE_FOOTAGE_PLANNED,
                    "state": STATE_BLOCKED,
                    "blocking_reasons": [REASON_PACKAGE_UNREADABLE],
                },
                None,
            )
        cost = plan.cascade.to_dict()
        economics = plan.to_dict()["unit_economics"]
        return (
            {
                "key": STAGE_FOOTAGE_PLANNED,
                "state": STATE_DONE,
                "candidate_count": plan.candidate_count,
                "watched_count": plan.watched_count,
                "upload_megabytes": round(plan.upload_megabytes, 1),
                "cost_jpy": round(float(cost["total_jpy"]), 2),
                "budget_jpy": round(float(cost["budget_jpy"]), 2),
                "within_budget": bool(cost["within_budget"]),
                "tightened_to_fit": bool(cost["tightened_to_fit"]),
                # Gate 7: what this ride costs to make, against what a
                # subscription can afford. Counts and money, nothing else.
                "per_ride_jpy": economics["total_jpy"],
                "fits_tier_100": economics["tiers"]["tier-100"]["fits"],  # type: ignore[index]
                "fits_tier_300": economics["tiers"]["tier-300"]["fits"],  # type: ignore[index]
            },
            plan,
        )

    def _copies_prepared_stage(self, plan: AnalysisRunPlan | None) -> dict[str, object]:
        """How many of the copies a run would send already exist."""
        if plan is None:
            return {"key": STAGE_COPIES_PREPARED, "state": STATE_BLOCKED, "prepared_count": 0}
        directory = self.package_directory / PROXY_DIRECTORY_NAME
        wanted = plan.watched_candidates
        present = 0
        total_bytes = 0
        for candidate in wanted:
            copy = directory / f"{candidate.event_id}.mp4"
            if copy.is_file() and not copy.is_symlink():
                size = copy.stat().st_size
                if size > 0:
                    present += 1
                    total_bytes += size
        if present == 0:
            state = STATE_PENDING
        elif present < len(wanted):
            state = STATE_IN_PROGRESS
        else:
            state = STATE_DONE
        return {
            "key": STAGE_COPIES_PREPARED,
            "state": state,
            "prepared_count": present,
            "wanted_count": len(wanted),
            "measured_megabytes": round(total_bytes / 1_000_000, 1),
        }

    def _footage_judged_stage(self, plan: AnalysisRunPlan | None) -> dict[str, object]:
        """Whether the model has been paid, and for how many windows."""
        if plan is None:
            return {"key": STAGE_FOOTAGE_JUDGED, "state": STATE_BLOCKED, "judged_count": 0}
        record = self.package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
        partial = self.package_directory / PARTIAL_RECORD_FILE_NAME
        wanted = plan.watched_count

        if record.is_file() and not record.is_symlink():
            try:
                judged = load_video_analysis_record(record)
            except (OSError, ValueError, KeyError, TypeError):
                return {
                    "key": STAGE_FOOTAGE_JUDGED,
                    "state": STATE_BLOCKED,
                    "judged_count": 0,
                    "blocking_reasons": [REASON_JUDGEMENT_UNREADABLE],
                }
            providers = {item.analysis.analysis_provider for item in judged.analysed}
            if not providers <= BOUGHT_ANALYSIS_PROVIDERS:
                # A stub's judgement looks exactly like a bought one, and a
                # film cut from it would show invented scores as evidence.
                return {
                    "key": STAGE_FOOTAGE_JUDGED,
                    "state": STATE_BLOCKED,
                    "judged_count": len(judged.analysed),
                    "blocking_reasons": [REASON_JUDGEMENT_UNBOUGHT],
                }
            return {
                "key": STAGE_FOOTAGE_JUDGED,
                "state": STATE_DONE,
                "judged_count": len(judged.analysed),
                "wanted_count": wanted,
            }

        if partial.is_file() and not partial.is_symlink():
            try:
                so_far = len(load_video_analysis_record(partial).analysed)
            except (OSError, ValueError, KeyError, TypeError):
                so_far = 0
            return {
                "key": STAGE_FOOTAGE_JUDGED,
                "state": STATE_IN_PROGRESS,
                "judged_count": so_far,
                "wanted_count": wanted,
            }

        return {
            "key": STAGE_FOOTAGE_JUDGED,
            "state": STATE_PENDING,
            "judged_count": 0,
            "wanted_count": wanted,
        }


def _plan_failure_reason(message: str) -> str:
    if "no footage inside the ride" in message:
        return REASON_NO_FOOTAGE_IN_RIDE
    if "no cascade fits" in message:
        return REASON_OVER_BUDGET
    return REASON_PACKAGE_UNREADABLE


def _next_action(stages: list[dict[str, object]], film_action: str) -> str:
    """The one thing to do next, judged path first.

    Once the judgement is bought the film's own status knows the rest, so
    its answer is passed through unchanged.
    """
    by_key = {str(stage["key"]): stage for stage in stages}
    planned = by_key[STAGE_FOOTAGE_PLANNED]
    if planned["state"] == STATE_BLOCKED:
        return ACTION_RESOLVE_BLOCKING
    judged = by_key[STAGE_FOOTAGE_JUDGED]
    if judged["state"] == STATE_BLOCKED:
        return ACTION_RESOLVE_BLOCKING
    if judged["state"] == STATE_IN_PROGRESS:
        return ACTION_WAIT_FOR_JUDGEMENT
    if judged["state"] == STATE_PENDING:
        prepared = by_key[STAGE_COPIES_PREPARED]
        if prepared["state"] != STATE_DONE:
            return ACTION_PREPARE_COPIES
        return ACTION_APPROVE_AND_JUDGE
    return film_action
