"""Hold a window as long as its motion earns, inside E-2's rank tier.

docs/research-touring-video-editing-ja.md §3's reading of the numbers:
a shot's length should not come from rank alone, because the same eight
seconds reads as long when the scenery barely changes and short when it
flies past ("尺は順位だけでなく画面内の変化量で決めるべき（変化が少ない
窓ほど短く）"). The research also widens each rank tier from one fixed
number into a range -- the best windows 8 to 10 seconds, the ordinary
rest 5 to 7, the unranked connectors 3 to 4 -- and asks that the same
length never plays three times running.

This module is the standalone function that range asks for: given a
window's rank and the one motion reading app.analysis_look already
measures (WindowLook.motion, FFmpeg's mean frame-to-frame difference on
the 1fps proxy), it places the hold somewhere in its tier's range by how
much that window moves relative to the others chosen alongside it. A
window that barely moves gets the short end of its tier; one that moves
the most gets the long end.

Nothing here touches a proxy, a path, or an asset id -- only the motion
number app.analysis_look already produced and the rank
app.gemini_selection already assigned. It does not replace
app.story_pacing.hold_for or wire into app.story_pacing.footage_for; the
range this trades for a fixed number changes every rendered clip's
length, and that is a rendering-facing choice the film's owner should
see before it plays, not something a code-only change should switch on
by itself.

The same research paragraph names a second, independent choice: a
twelve-second judged window need not be cut from its own start. Given the
per-second motion readings across the window (the same frame-difference
signal app.analysis_look averages away, kept here instead of thrown out),
`choose_half_by_motion` says whether the first six seconds or the last
six carry more of the window's motion, and `trim_bounds_for_half` turns
that choice into the offsets a cut would start and end at. Like the hold
range above, this decides nothing about a rendered clip by itself -- it
is the function a future wiring into app.story_pacing's cut-from-the-
window-start rule would call, once the film's owner has seen a window cut
from its second half rather than its first.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from enum import StrEnum

HoldRange = tuple[float, float]

# The three tiers of docs/research-touring-video-editing-ja.md §3, widened
# from app.story_pacing's fixed LONG/MEDIUM/SHORT_HOLD_S into the ranges
# the research names: best-of-best, ordinary, and connector.
LONG_HOLD_RANGE_S: HoldRange = (8.0, 10.0)
MEDIUM_HOLD_RANGE_S: HoldRange = (5.0, 7.0)
SHORT_HOLD_RANGE_S: HoldRange = (3.0, 4.0)

# Same cutoff app.story_pacing.hold_for uses: the model's best few ranks
# earn the top tier, the rest of what it ranked the middle one.
LONG_HOLD_RANKS = 5


class StoryHoldError(ValueError):
    """Raised when a hold cannot be computed from what it is given."""


def hold_range_for(rank: int | None) -> HoldRange:
    """Which tier's range a window earns, from where the model ranked it.

    Mirrors app.story_pacing.hold_for's cutoffs exactly, only returning
    the tier's (low, high) seconds instead of one fixed number.
    """
    if rank is None:
        return SHORT_HOLD_RANGE_S
    if rank <= LONG_HOLD_RANKS:
        return LONG_HOLD_RANGE_S
    return MEDIUM_HOLD_RANGE_S


def hold_from_motion(
    rank: int | None,
    motion: float,
    *,
    motion_floor: float,
    motion_ceiling: float,
) -> float:
    """Where in its rank tier's range a window's motion places its hold.

    ``motion_floor`` and ``motion_ceiling`` are the least and most motion
    seen across the windows being held together (see
    ``hold_all_from_motion``) -- a window's own motion means nothing
    without the others it will play beside. A window at the floor gets
    its tier's shortest length; one at the ceiling gets the longest;
    a floor equal to the ceiling (every window moves alike, or there is
    only one) places every window at its tier's midpoint rather than
    dividing by zero.
    """
    if not math.isfinite(motion) or motion < 0:
        raise StoryHoldError("motion is a non-negative frame-difference reading")
    if not math.isfinite(motion_floor) or motion_floor < 0:
        raise StoryHoldError("motion is a non-negative frame-difference reading")
    if not math.isfinite(motion_ceiling):
        raise StoryHoldError("motion is a non-negative frame-difference reading")
    if motion_ceiling < motion_floor:
        raise StoryHoldError("the motion ceiling cannot be below its floor")
    low, high = hold_range_for(rank)
    if motion_ceiling == motion_floor:
        fraction = 0.5
    else:
        fraction = (motion - motion_floor) / (motion_ceiling - motion_floor)
        fraction = min(1.0, max(0.0, fraction))
    return low + fraction * (high - low)


def hold_all_from_motion(
    ranked_motions: Sequence[tuple[str, int | None, float]],
) -> dict[str, float]:
    """Hold every window in a set from motion, then break up three alike.

    ``ranked_motions`` is ``(event_id, rank, motion)`` for every window,
    in the order the film will play them -- the same order the run of
    three alike is walked in, matching
    app.story_pacing.footage_for's own middle-of-three nudge. The floor
    and ceiling every window is placed against come from this same set,
    so a chapter of uniformly calm footage still spreads across its
    tiers' full ranges rather than collapsing to one motion reading
    against some other chapter's extremes.

    A run of three equal holds is nudged at the middle one, same as
    footage_for: pushed to its own tier's other end (long stays long,
    short stays short) so three metronome-even cuts never play running.
    """
    if not ranked_motions:
        return {}
    motions = [motion for _, _, motion in ranked_motions]
    floor, ceiling = min(motions), max(motions)
    ranks_by_id = {event_id: rank for event_id, rank, _ in ranked_motions}
    holds = {
        event_id: hold_from_motion(rank, motion, motion_floor=floor, motion_ceiling=ceiling)
        for event_id, rank, motion in ranked_motions
    }
    ordered_ids = [event_id for event_id, _, _ in ranked_motions]
    values = [holds[event_id] for event_id in ordered_ids]
    for index in range(1, len(values) - 1):
        if values[index - 1] == values[index] == values[index + 1]:
            low, high = hold_range_for(ranks_by_id[ordered_ids[index]])
            nudged = high if values[index] <= low + (high - low) / 2 else low
            values[index] = nudged
            holds[ordered_ids[index]] = nudged
    return holds


class WindowHalf(StrEnum):
    """Which six seconds of a twelve-second judged window earns the cut."""

    FIRST = "first"
    SECOND = "second"


# The research's own number: a judged window is twelve seconds, a cut
# from it six.
DEFAULT_HALF_DURATION_S = 6.0


def motion_by_half(motion_series: Sequence[float]) -> tuple[float, float]:
    """The mean motion of a window's first half and its second half.

    ``motion_series`` is the per-second frame-difference readings across
    the window, in time order -- the same signal
    app.analysis_look.measure_look already computes as FFmpeg's YDIF
    before averaging it into one number. The series is split at its
    midpoint; an odd reading in the middle joins the second half, so a
    thirteen-sample window (a twelve-second one plus the frame the first
    difference has nothing to compare against) still splits into six and
    seven rather than favouring one half by construction.
    """
    if len(motion_series) < 2:
        raise StoryHoldError("a window needs at least two motion readings to split")
    for value in motion_series:
        if not math.isfinite(value) or value < 0:
            raise StoryHoldError("motion is a non-negative frame-difference reading")
    midpoint = len(motion_series) // 2
    first_half = motion_series[:midpoint]
    second_half = motion_series[midpoint:]
    return statistics.mean(first_half), statistics.mean(second_half)


def choose_half_by_motion(motion_series: Sequence[float]) -> WindowHalf:
    """Which half of a window moves more, first or second.

    A tie -- both halves move alike, including a window that barely moves
    at all -- keeps the first half, the same seconds
    app.story_pacing already cuts from today. So this only ever moves a
    cut's start when the second half demonstrably earns it.
    """
    first_mean, second_mean = motion_by_half(motion_series)
    return WindowHalf.SECOND if second_mean > first_mean else WindowHalf.FIRST


def trim_bounds_for_half(
    window_duration_s: float,
    half: WindowHalf,
    *,
    half_duration_s: float = DEFAULT_HALF_DURATION_S,
) -> tuple[float, float]:
    """The (start, end) offsets, in seconds from the window's own start, to cut.

    A window shorter than ``half_duration_s`` has no spare half to choose
    between -- both halves clamp to the whole window rather than asking
    for seconds the footage does not have.
    """
    if window_duration_s <= 0:
        raise StoryHoldError("a window needs a positive duration")
    if half_duration_s <= 0:
        raise StoryHoldError("a half needs a positive duration")
    if half_duration_s >= window_duration_s:
        return 0.0, window_duration_s
    if half is WindowHalf.FIRST:
        return 0.0, half_duration_s
    return window_duration_s - half_duration_s, window_duration_s
