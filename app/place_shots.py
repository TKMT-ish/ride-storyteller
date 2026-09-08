"""The picture of each place the ride stopped at, and of where the day began and ended.

The owner's notes (2026-09-07): a stop needs its arrival, its place and
its leaving; the fuel stop that vanished must come back; the museum on
day 2 should be the bike outside it, not the exhibit inside; the lunch
places were missing altogether; and a film may end on the motel's
reception. The arrival and the leaving are the fixed shots
(app.fixed_shots). This module chooses the picture of the place: among
the windows the camera saw inside the stop, the one that shows where the
bike is -- standing, pulling in, a forecourt, a café front, a lookout --
outdoors, without the rider filling the frame, and never a home.

The same reading at the day's two ends picks a picture of the lodging:
the motel entrance the camera saw after the bike came to rest, or before
it set off.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts import VideoAnalysis
from app.gemini_selection import JudgedCandidate
from app.rider_in_frame import RIDER_LARGE, RIDER_NONE, RIDER_SMALL, rider_fills_the_frame
from app.stop_kinds import (
    StopKind,
    aboard_a_ferry,
    at_a_private_residence,
    indoors,
    place_kind_of,
    riding_aboard,
    spot_name,
    stop_kind,
)

# A window may begin this long before the track says the ride stopped and
# still be the stop's own picture (the clocks, the roll to a standstill).
PLACE_SHOT_LEAD_S = 30.0
# The lodging shows within this long of the day's own ends.
LODGING_WITHIN_S = 15 * 60.0
# Words the older records use when the picture is of a place the bike stands at.
_STANDING_WORDS = re.compile(
    r"\bstationary\b|\bstatic (?:view|shot)\b|\bparked\b|\bstopped\b|\bpulling (?:in|into|off)\b"
    r"|\bturning into\b|\bentrance\b|\bforecourt\b|\bcar park\b|\bparking lot\b",
    re.IGNORECASE,
)
# The subjects the judge names when the picture is of a place.
_PLACE_SUBJECTS = frozenset({"rest_stop", "landmark", "cityscape"})


@dataclass(frozen=True)
class StopPicture:
    """What a stop was, and the window that shows its place, if one does."""

    start_time: datetime
    end_time: datetime
    kind: StopKind
    spot: str | None
    event_id: str | None


def windows_inside(
    judged: Sequence[JudgedCandidate],
    start: datetime,
    end: datetime,
    *,
    lead_s: float = PLACE_SHOT_LEAD_S,
) -> tuple[JudgedCandidate, ...]:
    """The judged windows that begin inside the stop, a little lead allowed."""
    lead = timedelta(seconds=lead_s)
    return tuple(
        sorted(
            (c for c in judged if start - lead <= c.start_time <= end and c.analysis is not None),
            key=lambda c: c.start_time,
        )
    )


def shows_the_place(analysis: VideoAnalysis) -> bool:
    """Whether the picture is of where the bike is, rather than of the road ahead."""
    if analysis.stationary == "yes" or analysis.road_event == "pulling_in":
        return True
    if analysis.highlight_subject in _PLACE_SUBJECTS:
        return True
    if place_kind_of(analysis) is not None:
        return True
    return _STANDING_WORDS.search(analysis.visual_description) is not None


def picture_of(
    inside: Sequence[JudgedCandidate],
    *,
    end: datetime,
    kind: StopKind,
    taken: Collection[str] = (),
) -> str | None:
    """The one window that best shows the place, or None when none does.

    Outdoors before indoors, the place's own kind before another, a
    rider-free frame before one the rider fills, the bike at rest or
    pulling in before the road ahead, then the model's score. A stop's
    picture is a fixed shot like the arrival and the leaving, so the
    rider in the mirror does not rule it out (the owner, 2026-09-07); a
    home does. The seconds of the leaving belong to the leaving's own
    shot. A stop whose windows all look down the road has no picture: the
    arrival and the leaving say enough.

    A ferry's stop is the exception: its picture is the boarding -- the
    bike riding up the ramp -- and failing that the last outdoor window
    of the wait that is not already out at sea.

    The windows the film already keeps -- the arrival, the leaving -- are
    passed in `taken` and are not chosen again; nothing else about the
    stop's own minutes is ruled out, because the bike in the forecourt as
    the ride packs up is often the only picture of the place there is
    (the owner, 2026-09-07: the museum's own hall was the wrong shot; the
    bike outside it was the right one).
    """
    best: tuple[tuple, str] | None = None
    for candidate in inside:
        analysis = candidate.analysis
        if analysis is None or candidate.event_id in taken:
            continue
        if at_a_private_residence(analysis):
            continue
        if not shows_the_place(analysis):
            continue
        seen = place_kind_of(analysis)
        inside_a_building = 1 if indoors(analysis) else 0
        if kind is StopKind.FERRY:
            key: tuple = (
                0 if riding_aboard(analysis) else 1,
                inside_a_building,
                1 if aboard_a_ferry(analysis) else 0,
                -candidate.start_time.timestamp(),
            )
        else:
            key = (
                inside_a_building,
                0 if seen is None or seen is kind or kind in (StopKind.LUNCH, StopKind.MEAL) else 1,
                _rider_rank(analysis),
                0 if analysis.stationary == "yes" or analysis.road_event == "pulling_in" else 1,
                -candidate.score(),
            )
        if best is None or key < best[0]:
            best = (key, candidate.event_id)
    return best[1] if best is not None else None


def _rider_rank(analysis: VideoAnalysis) -> int:
    """How much the rider is in the way: an answered "none" beats an unasked window.

    The owner's day-5 note (2026-09-07): a stop's picture showed a person
    filling the frame. The model never described them, so the words could
    not say so -- but it did say "none" about other windows of that stop,
    and those are the ones to take.
    """
    if rider_fills_the_frame(analysis):
        return 3
    if analysis.rider_visible == RIDER_NONE:
        return 0
    if analysis.rider_visible == RIDER_SMALL:
        return 2
    return 1 if analysis.rider_visible != RIDER_LARGE else 3


def stop_pictures(
    judged: Sequence[JudgedCandidate],
    stops: Sequence[tuple[datetime, datetime]],
    *,
    taken: Collection[str] = (),
    local_offset_s: float | None = None,
) -> tuple[StopPicture, ...]:
    """Every stop with its kind, its spot's name where one was read, and its picture."""
    pictures: list[StopPicture] = []
    for start, end in stops:
        inside = windows_inside(judged, start, end)
        analyses = [c.analysis for c in inside if c.analysis is not None]
        hour = None
        if local_offset_s is not None:
            local = start + timedelta(seconds=local_offset_s)
            hour = local.hour + local.minute / 60.0
        kind = stop_kind(analyses, duration_s=(end - start).total_seconds(), local_hour=hour)
        pictures.append(
            StopPicture(
                start_time=start,
                end_time=end,
                kind=kind,
                spot=spot_name(analyses),
                event_id=picture_of(inside, end=end, kind=kind, taken=taken),
            )
        )
    return tuple(pictures)


def lodging_picture(
    judged: Sequence[JudgedCandidate],
    *,
    at: datetime,
    after: bool,
    taken: Collection[str] = (),
    within_s: float = LODGING_WITHIN_S,
) -> str | None:
    """The window that shows the lodging, after the day's arrival or before its departure.

    The model must have placed the window at a lodging -- a motel entrance,
    a reception, a hotel's forecourt -- and outdoors; the rider must not
    fill it, and it must not be a home. The bike moving through the
    grounds beats it standing; the model's score decides the rest.
    """
    if within_s <= 0:
        raise ValueError("the lodging reach must be positive")
    reach = timedelta(seconds=within_s)
    lo, hi = (at, at + reach) if after else (at - reach, at)
    best: tuple[tuple[int, float], str] | None = None
    for candidate in judged:
        analysis = candidate.analysis
        if analysis is None or candidate.event_id in taken:
            continue
        if not lo <= candidate.start_time <= hi:
            continue
        if place_kind_of(analysis) is not StopKind.LODGING or indoors(analysis):
            continue
        if rider_fills_the_frame(analysis) or at_a_private_residence(analysis):
            continue
        key = (1 if analysis.stationary == "yes" else 0, -candidate.score())
        if best is None or key < best[0]:
            best = (key, candidate.event_id)
    return best[1] if best is not None else None


def pictures_by_id(pictures: Sequence[StopPicture]) -> Mapping[str, StopPicture]:
    return {p.event_id: p for p in pictures if p.event_id is not None}
