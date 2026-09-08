"""Look for windows the ride was not moving through, before paying for them.

Gate 7 assumed a free local screen would halve the bill: drop the windows
where nothing happens -- a stop, a car park, a queue -- and buy only the
rest. Measured on both real rides on 2026-09-04, it does not.

Two free signals were tried on every window of both rides.

*Frame difference* over the copies already made for the judgement -- the
mean absolute change between consecutive frames of the 1 fps proxy --
separates almost nothing. On a motorcycle the whole frame moves even at a
red light, because the camera is on the rider. Held below the quietest
window either film adopted, it drops 3 windows of 173 and 1 of 92: under
two percent.

*GPS speed* is a truer reading of "the ride was stopped", and drops more:
13 of 173 and 10 of 92, seven to eleven percent. But it is not safe. Both
films use stopped windows -- a fuel stop, a junction, an arrival -- and at
every threshold tried it removed windows the finished films had adopted:
two of twenty on the first ride, three of twenty on the second, one of
them the highest-scored window of its ride (0.80). Buying one window per
stop rather than one per window loses less and still loses one, for a
three percent saving.

Standing still is not the same as having nothing to show, and these rides
do not stand still for long. The largest saving that never cost a film a
window was about two percent -- half a yen against a bill of twenty-eight.
The subscription has to be paid for by the size of the job -- ranking
instead of judging, a longer stride -- not by screening.

So this module measures and reports. **It drops nothing**, and nothing on
the paying path calls it. It is here because the measurement should be
repeatable on a ride that does sit in traffic for an hour, where the
answer could differ, and because it is free: it reads the GPS track that
is parsed anyway and opens no video.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from app.footage_candidates import (
    DEFAULT_STRIDE_S,
    DEFAULT_WINDOW_S,
    enumerate_footage_candidates,
)
from app.gps.events import EventThresholds
from app.gps.parser import parse_gpx
from app.local_pipeline import load_local_pipeline_inputs
from app.unit_economics import MEASURED_JUDGE_JPY_PER_WINDOW
from app.video import load_video_catalog

WINDOW_SCREENING_SCHEMA_VERSION = "window-screening-v1"

# One system, one definition of stopped: the threshold GPS events already
# use to call a ride halted.
DEFAULT_STILL_SPEED_MPS = EventThresholds().stop_speed_mps
# Walking pace. A bike pushed across a car park, or a rider walking round
# a museum with the camera running, is still at the same place; the
# question a halt answers is "is this the same place", not "is it still".
HALT_SPEED_MPS = 3.0


class AnalysisScreeningError(RuntimeError):
    """Raised when a ride's windows cannot be screened as asked."""


@dataclass(frozen=True)
class WindowStillness:
    """How fast the ride was moving through one window, per the GPS track."""

    event_id: str
    fastest_mps: float | None
    point_count: int

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("a stillness reading needs its window")
        if self.point_count < 0:
            raise ValueError("a window cannot hold a negative number of points")
        if self.fastest_mps is not None and self.fastest_mps < 0:
            raise ValueError("a speed cannot be negative")

    def is_still(self, speed_mps: float = DEFAULT_STILL_SPEED_MPS) -> bool:
        """Whether the track says the ride never got above a walking pace here.

        A window the track says nothing about is never called still. Not
        knowing and standing still are different, and only one of them is
        an argument for not looking.
        """
        return self.fastest_mps is not None and self.fastest_mps <= speed_mps


def measure_stillness(
    package_directory: Path,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    stride_s: float = DEFAULT_STRIDE_S,
) -> tuple[WindowStillness, ...]:
    """The fastest the ride went through each window, in ride order. Free.

    The windows are the same ones `plan_analysis_run` would price, drawn
    the same way from the catalogue and the track, so a reading here lines
    up with a window there. No video is opened and nothing is sent.
    """
    inputs = load_local_pipeline_inputs(package_directory / "local-pipeline-inputs.json")
    catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    route = parse_gpx(inputs.gpx_path)
    windows = enumerate_footage_candidates(
        catalog,
        route.summary.start_time,
        route.summary.end_time,
        window_s=window_s,
        stride_s=stride_s,
    )
    if not windows:
        raise AnalysisScreeningError("this package has no footage inside the ride to screen")

    # The track is in time order, so each window's points are one slice of
    # it rather than a scan of the whole track.
    stamps = [point.timestamp for point in route.points]
    readings: list[WindowStillness] = []
    for window in windows:
        first = bisect_left(stamps, window.start_time)
        last = bisect_right(stamps, window.end_time)
        speeds = [
            point.speed_mps for point in route.points[first:last] if point.speed_mps is not None
        ]
        readings.append(
            WindowStillness(
                event_id=window.candidate_id,
                fastest_mps=max(speeds) if speeds else None,
                point_count=len(speeds),
            )
        )
    return tuple(readings)


def still_windows(
    readings: tuple[WindowStillness, ...], *, speed_mps: float = DEFAULT_STILL_SPEED_MPS
) -> tuple[str, ...]:
    """The windows the ride never moved through, in ride order."""
    if speed_mps < 0:
        raise AnalysisScreeningError("a still speed cannot be negative")
    return tuple(reading.event_id for reading in readings if reading.is_still(speed_mps))


def windows_after_the_first_of_each_stop(
    readings: tuple[WindowStillness, ...], *, speed_mps: float = DEFAULT_STILL_SPEED_MPS
) -> tuple[str, ...]:
    """Every still window except the one that opens its stop, in ride order.

    A long stop yields window after window of the same parked view, and
    buying each of them again is the one saving in this family that has an
    argument behind it: pay once for a stop, not once every thirty seconds
    of it. Measured, it is still not free of cost -- see the module note.
    """
    still = [reading.is_still(speed_mps) for reading in readings]
    dropped: list[str] = []
    for index, is_still in enumerate(still):
        if is_still and index > 0 and still[index - 1]:
            dropped.append(readings[index].event_id)
    return tuple(dropped)


def screening_report(
    package_directory: Path,
    *,
    speed_mps: float = DEFAULT_STILL_SPEED_MPS,
    window_s: float = DEFAULT_WINDOW_S,
    stride_s: float = DEFAULT_STRIDE_S,
) -> dict[str, object]:
    """What screening this ride would save, and what it declines to do.

    Counts and money only: no window identifier, no time, no place, no
    path. Nothing here decides anything -- `drops_nothing` is the whole
    contract, and it is stated in the payload so a reader of the output
    does not have to take it on trust.
    """
    readings = measure_stillness(package_directory, window_s=window_s, stride_s=stride_s)
    still = still_windows(readings, speed_mps=speed_mps)
    per_stop = windows_after_the_first_of_each_stop(readings, speed_mps=speed_mps)
    unknown = sum(1 for reading in readings if reading.fastest_mps is None)
    return {
        "schema_version": WINDOW_SCREENING_SCHEMA_VERSION,
        "window_count": len(readings),
        "still_count": len(still),
        "unknown_count": unknown,
        "stop_count": len(still) - len(per_stop),
        "still_speed_mps": speed_mps,
        "would_save_jpy": {
            "dropping_every_still_window": round(len(still) * MEASURED_JUDGE_JPY_PER_WINDOW, 2),
            "keeping_one_window_per_stop": round(len(per_stop) * MEASURED_JUDGE_JPY_PER_WINDOW, 2),
        },
        "drops_nothing": True,
    }


def halts(
    readings: tuple[WindowStillness, ...], *, speed_mps: float = HALT_SPEED_MPS
) -> dict[str, int]:
    """Which windows belong to which halt, numbered in ride order.

    A halt is a run of consecutive windows through which the ride never got
    above walking pace or the track went quiet -- indoors, GPS is lost, and
    the museum the owner found the film full of showed up as a run of
    windows with no reading at all. A run counts only when at least one
    reading in it was actually measured at walking pace or below: a gap in
    the track on open road is not a place, and a run of nothing but silence
    is left alone.

    Windows on the move are absent from the result. Nothing here drops a
    window; it says which ones are the same place, so that whatever chooses
    can show a place once.
    """
    if speed_mps < 0:
        raise AnalysisScreeningError("a halt speed cannot be negative")
    result: dict[str, int] = {}
    number = 0
    run: list[WindowStillness] = []

    def close() -> None:
        nonlocal number
        anchored = any(
            reading.fastest_mps is not None and reading.fastest_mps <= speed_mps for reading in run
        )
        if anchored:
            number += 1
            for reading in run:
                result[reading.event_id] = number
        run.clear()

    for reading in readings:
        if reading.fastest_mps is None or reading.fastest_mps <= speed_mps:
            run.append(reading)
        else:
            close()
    close()
    return result
