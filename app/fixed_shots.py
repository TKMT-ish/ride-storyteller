"""The shots a film always carries: setting off, pulling in and out, arriving.

The owner's first rule (2026-09-06): the departure, every halt and the
arrival are in the film as a matter of course, cut on the moment. Each
moment the track proves (app.gps.moments) gets one window placed so that
the picture holds the change: a departure window starts three seconds
before the bike moves, an arrival window ends three seconds after it
stops. The window is bought and judged like any other -- the rider rule
still applies to it -- and then the selection keeps it whatever its score,
because a departure that scored 0.3 is still the departure.

The film side matches windows to moments by their start: a window that
begins within `FIXED_SHOT_TOLERANCE_S` of where the moment's window would
begin is that moment's shot. A moment with no such window (the camera was
off) is simply not shown; nothing is invented for it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from app.contracts import RoutePoint
from app.gps.moments import Moment, MomentKind, come_to_rest, set_off

# How much of the window stands still: before the move, or after the stop.
FIXED_SHOT_STILL_S = 3.0
# A fixed shot is held long enough to see the change happen, from its start.
FIXED_SHOT_HOLD_S = 8.0
# A window starting this close to the moment's own window is the same shot.
FIXED_SHOT_TOLERANCE_S = 3.0
# The GPS says when the ride moved; the picture may lag or lead by some
# seconds (the clocks, a creep before the roll-off). So each moment gets a
# fan of windows, one every FAN_STEP_S, and the model's answer -- setting
# off, pulling in, standing still -- chooses among them (the owner's
# day-1 note, 2026-09-07).
FAN_STEP_S = 10.0
FAN_LATER = (0.0, 1.0, 2.0)  # for moments where the change comes after: departures
FAN_EARLIER = (-2.0, -1.0, 0.0)  # for moments where the change comes before: arrivals
# The day's own departure: the GPS said "moving" while the bike still stood
# in the forecourt for half a minute (day 1), so this fan reaches further.
FAN_DAY_START = (0.0, 1.0, 2.0, 3.0, 4.0)


class _Window(Protocol):
    @property
    def event_id(self) -> str: ...
    @property
    def start_time(self) -> datetime: ...


# A day's departure or arrival the camera missed is moved to the nearest
# filmed moment, if the camera came on (or went off) within this long.
FILMED_WITHIN_S = 60 * 60.0


def filmed_moments(
    moments: Sequence[Moment],
    recordings: Sequence[tuple[datetime, datetime]],
    *,
    window_s: float,
    within_s: float = FILMED_WITHIN_S,
    points: Sequence[RoutePoint] = (),
) -> tuple[Moment, ...]:
    """The moments as the camera can show them.

    A halt's two ends the camera missed are dropped: there is nothing to
    show. The day's departure and arrival are different -- the owner
    wants the leaving and the arriving in the film -- so when the camera
    came on a little after the ride set off, the departure becomes the
    first filmed moment, and when it went off a little before the ride
    stopped, the arrival becomes the last; beyond `within_s` they are
    dropped too, rather than showing some other minute as the day's end.

    With the track (`points`), a departure moved to the camera's start is
    placed where the ride first gets going after the camera came on -- the
    owner's day 1 opened on the bike standing still with the rider in the
    mirror -- and an arrival where it last moved before the camera went
    off, when that lies inside the recording.
    """
    spans = sorted(recordings)
    window = timedelta(seconds=window_s)
    still = timedelta(seconds=FIXED_SHOT_STILL_S)
    kept: list[Moment] = []
    for moment in moments:
        start = fixed_shot_start(moment, window_s)
        end = start + window
        if any(a <= start and end <= b for a, b in spans):
            kept.append(moment)
            continue
        if moment.kind is MomentKind.DEPARTURE:
            later = [(a, b) for a, b in spans if a >= start and b - a >= window]
            if later and (later[0][0] - moment.at).total_seconds() <= within_s:
                came_on, went_off = later[0]
                at = came_on + still
                moving = set_off([p for p in points if p.timestamp >= came_on]) if points else None
                if moving is not None and moving - still + window <= went_off:
                    at = max(at, moving)
                kept.append(Moment(moment.kind, at))
        elif moment.kind is MomentKind.ARRIVAL:
            earlier = [(a, b) for a, b in spans if b <= end and b - a >= window]
            if earlier and (moment.at - earlier[-1][1]).total_seconds() <= within_s:
                came_on, went_off = earlier[-1]
                at = went_off - still
                resting = (
                    come_to_rest([p for p in points if p.timestamp <= went_off]) if points else None
                )
                if resting is not None and resting + still - window >= came_on:
                    at = min(at, resting)
                kept.append(Moment(moment.kind, at))
    return tuple(kept)


def fixed_shot_start(moment: Moment, window_s: float) -> datetime:
    """Where a window of `window_s` begins so that it holds this moment."""
    if window_s <= FIXED_SHOT_STILL_S:
        raise ValueError("a fixed shot needs a window longer than its still part")
    if moment.kind in _CHANGE_COMES_AFTER:
        return moment.at - timedelta(seconds=FIXED_SHOT_STILL_S)
    return moment.at - timedelta(seconds=window_s - FIXED_SHOT_STILL_S)


# The moments whose change comes after the window's start: the bike rolls,
# joins, leaves, rides off the ferry. The others -- pulling in, arriving --
# end on the change instead.
_CHANGE_COMES_AFTER = frozenset(
    {
        MomentKind.DEPARTURE,
        MomentKind.HALT_DEPARTURE,
        MomentKind.HIGHWAY_ON,
        MomentKind.HIGHWAY_OFF,
        MomentKind.FERRY_OFF,
    }
)


def _fan(moment: Moment) -> tuple[float, ...]:
    if moment.kind is MomentKind.DEPARTURE:
        return FAN_DAY_START
    if moment.kind in _CHANGE_COMES_AFTER:
        return FAN_LATER
    return FAN_EARLIER


def fixed_shot_fan(moment: Moment, window_s: float) -> tuple[datetime, ...]:
    """Where the moment's candidate windows begin: its own start and the fan around it."""
    base = fixed_shot_start(moment, window_s)
    return tuple(base + timedelta(seconds=step * FAN_STEP_S) for step in _fan(moment))


def fixed_shot_starts(moments: Sequence[Moment], window_s: float) -> tuple[datetime, ...]:
    """The starts of every moment's candidate windows, in ride order."""
    return tuple(sorted(start for moment in moments for start in fixed_shot_fan(moment, window_s)))


def fixed_shots_for(
    windows: Iterable[_Window],
    moments: Sequence[Moment],
    *,
    window_s: float,
    tolerance_s: float = FIXED_SHOT_TOLERANCE_S,
) -> dict[str, Moment]:
    """Every candidate window of every moment, by event id. Unmatched moments are absent.

    A moment owns each window of its fan that some judged window starts
    within `tolerance_s` of; `choose_shots` then keeps one per moment.
    """
    if tolerance_s < 0:
        raise ValueError("a tolerance cannot be negative")
    ordered = sorted(windows, key=lambda w: w.start_time)
    shots: dict[str, Moment] = {}
    for moment in moments:
        for wanted in fixed_shot_fan(moment, window_s):
            nearest = min(
                (w for w in ordered if w.event_id not in shots),
                key=lambda w: abs((w.start_time - wanted).total_seconds()),
                default=None,
            )
            if nearest is None:
                continue
            if abs((nearest.start_time - wanted).total_seconds()) <= tolerance_s:
                shots[nearest.event_id] = moment
    return shots


# What the model should have seen in the window for each kind of moment.
_EXPECTED_EVENT: dict[MomentKind, tuple[str, ...]] = {
    MomentKind.DEPARTURE: ("setting_off",),
    MomentKind.HALT_DEPARTURE: ("setting_off",),
    MomentKind.ARRIVAL: ("pulling_in",),
    MomentKind.HALT_ARRIVAL: ("pulling_in",),
    MomentKind.HIGHWAY_ON: ("joining_highway",),
    MomentKind.HIGHWAY_OFF: ("leaving_highway",),
    MomentKind.FERRY_OFF: ("setting_off",),
}


class _Judged(Protocol):
    @property
    def event_id(self) -> str: ...
    @property
    def start_time(self) -> datetime: ...
    @property
    def analysis(self) -> object: ...


def choose_shots(
    fan: Mapping[str, Moment], windows: Iterable[_Judged], *, window_s: float
) -> dict[str, Moment]:
    """One window per moment: the one whose picture shows the moment.

    Among a moment's candidate windows the model's answers decide -- the
    expected road event first (setting off, pulling in, joining or leaving
    the highway), then a bike that moved over one that stood still, then
    the window nearest the moment. A window the model never judged loses
    to any judged one. The rider in the mirror does not disqualify these
    shots (the owner, 2026-09-07): the moment matters more.
    """
    by_id = {w.event_id: w for w in windows}
    grouped: dict[Moment, list[str]] = {}
    for event_id, moment in fan.items():
        if event_id in by_id:
            grouped.setdefault(moment, []).append(event_id)
    chosen: dict[str, Moment] = {}
    for moment, event_ids in grouped.items():
        wanted = fixed_shot_start(moment, window_s)

        def rank(event_id: str) -> tuple[int, int, int, float]:
            window = by_id[event_id]
            analysis = window.analysis
            if analysis is None:
                return (1, 1, 1, 0.0)
            event = str(getattr(analysis, "road_event", "unknown"))
            still = str(getattr(analysis, "stationary", "unknown"))
            expected = 0 if event in _EXPECTED_EVENT.get(moment.kind, ()) else 1
            moving = 0 if still == "no" else (1 if still == "unknown" else 2)
            return (0, expected, moving, abs((window.start_time - wanted).total_seconds()))

        best = min(event_ids, key=rank)
        chosen[best] = moment
    return chosen
