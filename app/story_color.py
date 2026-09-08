"""Bring adjacent windows' brightness together (research E-6).

docs/research-touring-video-editing-ja.md §6: "露出・WB・コントラスト・
彩度をクリップ間で合わせる。不揃いは絶景でも素人の印" -- one window shot
into the sun and the next in a tunnel's shadow reads as a mistake even
when both are otherwise good footage. `app.analysis_look.WindowLook`
already measures each window's mean luma (FFmpeg `signalstats.YAVG` on
the 1fps judgement proxy) for the look-alike check; this module is the
other use of that same number.

Only exposure (brightness) is covered here, not contrast or white
balance -- `WindowLook` has no contrast or colour-temperature reading to
correct from, and inventing one without a proxy measurement to test it
against would be guessing. Nothing here touches a proxy, a path, or an
FFmpeg process: it takes the luma numbers app.analysis_look already
produced and returns the correction each window's picture would need
under FFmpeg's `eq` filter (`eq=brightness=<value>`, a shift in -1..1)
to read closer to the group's shared brightness. Wiring that filter into
app.story_film's render and re-rendering both rides is left for later --
every clip's picture would change, and that is a rendering-facing choice
the film's owner should see before it plays, the same reasoning
app.story_hold gives for not wiring its own hold range and cut half by
itself.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

# How far a window's brightness may be pushed toward the group's target,
# in the same -1..1 units as FFmpeg's `eq` filter's `brightness` option.
# A window shot in a tunnel is dark for a reason; correcting it all the
# way to the target would flatten it (or blow out a window already near
# white). This caps the correction rather than closing the whole gap.
DEFAULT_MAX_BRIGHTNESS_CORRECTION = 0.12

# WindowLook.luma is FFmpeg signalstats.YAVG, an 8-bit mean: 0..255.
_LUMA_RANGE = 255.0


def _validate_luma(value: float, *, label: str = "a luma") -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite non-negative number")


def luma_target(lumas: Sequence[float]) -> float:
    """The shared brightness a group of windows should read as.

    The median, not the mean, so one badly over- or under-exposed window
    does not drag every other window's correction toward it.
    """
    if not lumas:
        raise ValueError("need at least one window's luma to find a target")
    for value in lumas:
        _validate_luma(value)
    return statistics.median(lumas)


def brightness_correction(
    luma: float,
    target: float,
    *,
    max_correction: float = DEFAULT_MAX_BRIGHTNESS_CORRECTION,
) -> float:
    """The `eq=brightness=` shift that moves `luma` toward `target`.

    Positive brightens a dark window; negative dims a bright one. The
    correction is the gap between the two, scaled from the 0..255 luma
    range into the filter's -1..1 range, then clamped to
    `max_correction` in either direction -- closing the whole gap in one
    step is exactly the flattening the research warns against.
    """
    _validate_luma(luma, label="luma")
    _validate_luma(target, label="target")
    if not math.isfinite(max_correction) or max_correction <= 0:
        raise ValueError("max_correction must be a finite positive number")
    raw = (target - luma) / _LUMA_RANGE
    return max(-max_correction, min(max_correction, raw))


def brightness_corrections(
    lumas: Sequence[float],
    *,
    target: float | None = None,
    max_correction: float = DEFAULT_MAX_BRIGHTNESS_CORRECTION,
) -> tuple[float, ...]:
    """`brightness_correction` for every window in `lumas`, in order.

    `target` defaults to `luma_target(lumas)` (the group's own median);
    pass an explicit target to match a group against a brightness that
    is not itself one of the windows (a chapter's opener, for instance).
    """
    if not lumas:
        raise ValueError("need at least one window's luma to correct")
    resolved_target = target if target is not None else luma_target(lumas)
    return tuple(
        brightness_correction(luma, resolved_target, max_correction=max_correction)
        for luma in lumas
    )
