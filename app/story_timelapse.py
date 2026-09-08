"""Fill a long halt's or an unfilmed gap's screen time with a timelapse (research E-7).

docs/research-touring-video-editing-ja.md §6/§7 ("長い停止の前後・未撮影区間を
1fpsコピーのタイムラプスで3〜5秒（小窓）。時間の経過を見せる"): a long halt or an
unfilmed stretch currently earns nothing but a static text card
(app.gap_chapters, app.ride_chapters's long-halt handling) -- true to the GPS
evidence, but a card is a pause in the film's motion. The system already keeps
a 1fps low-resolution proxy copy of every day's footage for judging
(app.analysis_proxy); playing that copy back at its own rate over the span it
already covers reads as a timelapse for free -- no new capture, no model call.

Only the decision is made here, not the render: which spans are worth a
timelapse at all (research: a *long* halt, or a gap that already earns its
own card -- a five-minute lunch stop is still just a stop) and how long the
timelapse plays (research's 3-5 second window, longer for a longer span
behind it, but never past what a small inset can hold). Nothing here touches
a proxy path, a coordinate, or an FFmpeg process; wiring a picture-in-picture
timelapse into app.story_film's render is a rendering decision for later --
the film's owner should see it play before it is baked into every day's
render, the same reasoning app.story_color and app.story_audio give for
leaving their own corrections unwired.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

# A halt shorter than this is an ordinary pause, not a "long stop" whose
# passage of time is itself part of the story. Matches
# app.ride_chapters.LONG_HALT_S, the existing threshold for a halt earning
# its own arrival/departure moments -- kept as this module's own constant
# rather than an import so a decision-only module stays free of the still-
# changing story-construction modules, the same choice app.story_color and
# app.story_audio make.
MINIMUM_HALT_S = 15 * 60.0

# An unfilmed stretch shorter than this does not earn its own gap card
# either (app.journey_gaps.DEFAULT_MINIMUM_GAP_S) -- too brief a timelapse
# would read as a flicker, not a passage of time.
MINIMUM_GAP_S = 60.0

# Research E-7's own figures: a timelapse reads as a considered edit
# somewhere between these two lengths, however long the span behind it.
MINIMUM_DISPLAY_S = 3.0
MAXIMUM_DISPLAY_S = 5.0

# The source span length at which the on-screen timelapse reaches
# MAXIMUM_DISPLAY_S. A stop longer than this is compressed harder, not
# shown any longer -- that is the point of a timelapse.
DEFAULT_SATURATES_AT_S = 3600.0


class TimelapseSourceKind(StrEnum):
    """Which kind of screen time this timelapse would stand in for."""

    LONG_HALT = "long_halt"
    UNFILMED_GAP = "unfilmed_gap"


class TimelapseDecisionError(ValueError):
    """Raised when a timelapse decision cannot be made safely."""


@dataclass(frozen=True)
class TimelapseDecision:
    """A span worth showing as timelapse, and for how long."""

    kind: TimelapseSourceKind
    source_duration_s: float
    display_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.source_duration_s) or self.source_duration_s < 0:
            raise TimelapseDecisionError("source_duration_s must be a finite non-negative number")
        if not math.isfinite(self.display_s) or self.display_s <= 0:
            raise TimelapseDecisionError("display_s must be a finite positive number")


def _validate_duration(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise TimelapseDecisionError("duration_s must be a finite non-negative number")


def is_timelapse_candidate(kind: TimelapseSourceKind, duration_s: float) -> bool:
    """Whether a span this long, of this kind, is worth a timelapse at all.

    A long halt needs `MINIMUM_HALT_S` of real time before its passage is
    itself part of the story; an unfilmed gap needs only the shorter
    `MINIMUM_GAP_S` it already takes to earn a text card, because there the
    alternative is not a shorter card -- it is the same card the film
    already shows, with nothing moving behind it.
    """
    _validate_duration(duration_s)
    threshold = MINIMUM_HALT_S if kind is TimelapseSourceKind.LONG_HALT else MINIMUM_GAP_S
    return duration_s >= threshold


def timelapse_display_s(
    duration_s: float,
    *,
    minimum_display_s: float = MINIMUM_DISPLAY_S,
    maximum_display_s: float = MAXIMUM_DISPLAY_S,
    saturates_at_s: float = DEFAULT_SATURATES_AT_S,
) -> float:
    """How long, in on-screen seconds, a `duration_s`-long span plays as timelapse.

    Linear between `minimum_display_s` at zero real seconds and
    `maximum_display_s` at `saturates_at_s` real seconds or more -- a
    twenty-minute stop and a two-hour stop should not look identical, but
    neither should a small picture-in-picture inset hold past the length
    research calls comfortable.
    """
    _validate_duration(duration_s)
    if not math.isfinite(minimum_display_s) or minimum_display_s <= 0:
        raise TimelapseDecisionError("minimum_display_s must be a finite positive number")
    if not math.isfinite(maximum_display_s) or maximum_display_s <= minimum_display_s:
        raise TimelapseDecisionError(
            "maximum_display_s must be a finite number greater than minimum_display_s"
        )
    if not math.isfinite(saturates_at_s) or saturates_at_s <= 0:
        raise TimelapseDecisionError("saturates_at_s must be a finite positive number")
    fraction = min(1.0, duration_s / saturates_at_s)
    return minimum_display_s + fraction * (maximum_display_s - minimum_display_s)


def decide_timelapse(
    kind: TimelapseSourceKind,
    duration_s: float,
    *,
    minimum_display_s: float = MINIMUM_DISPLAY_S,
    maximum_display_s: float = MAXIMUM_DISPLAY_S,
    saturates_at_s: float = DEFAULT_SATURATES_AT_S,
) -> TimelapseDecision | None:
    """The timelapse decision for one span, or `None` if it is not worth one.

    A single entry point so a caller never has to remember to pair
    `is_timelapse_candidate` with `timelapse_display_s` itself.
    """
    if not is_timelapse_candidate(kind, duration_s):
        return None
    display_s = timelapse_display_s(
        duration_s,
        minimum_display_s=minimum_display_s,
        maximum_display_s=maximum_display_s,
        saturates_at_s=saturates_at_s,
    )
    return TimelapseDecision(kind=kind, source_duration_s=duration_s, display_s=display_s)


def decide_timelapses(
    spans: list[tuple[TimelapseSourceKind, float]],
) -> tuple[TimelapseDecision | None, ...]:
    """`decide_timelapse` for every span in `spans`, in order.

    A day's worth of long halts and unfilmed gaps can be planned in one
    call; a `None` in the result marks a span that stays a plain card.
    """
    if not spans:
        raise TimelapseDecisionError("need at least one span to plan timelapses for")
    return tuple(decide_timelapse(kind, duration_s) for kind, duration_s in spans)
