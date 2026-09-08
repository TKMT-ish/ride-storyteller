"""Splice adjacent windows' sound without a hard edit (research E-5).

docs/research-touring-video-editing-ja.md §5 ("隣り合う窓の音を0.5秒クロス
フェード、風切りの酷い窓は自動で−6dB（RMSで判定）"): two windows cut
together at a hard audio edge reads as a mistake the same way a hard light
jump does (E-6), and a window recorded with wind roaring straight into the
microphone is worse than the ride around it. Both are decided from a number
every window already has once someone measures it -- the window's own RMS
level -- the same shape app.story_color takes with luma for exposure.

Only the decision is made here, not the mix: a window's actual RMS is not
measured anywhere in this codebase yet, and app.story_film currently drops
every window's own audio outright ("The footage's own audio is dropped. It
is engine and wind noise..."), so whether footage audio is used at all --
and if so how a crossfade and an attenuation get wired into FFmpeg's filter
graph next to app.story_music's mix -- is a rendering decision for later,
the same reasoning app.story_color gives for not wiring its own correction.
This module only says, given RMS numbers, which windows need pulling down
and by how much, and names the crossfade length E-5 calls for so it stops
being a number someone has to remember.

Nothing here touches a proxy, a path, or an FFmpeg process.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

# Research E-5: "隣り合う窓の音を0.5秒クロスフェード" -- long enough that a
# splice doesn't click, short enough that it never reaches into a window's
# own content instead of just its cut edge (the shortest window S3 allows
# is several seconds).
CROSSFADE_SECONDS = 0.5

# How far above the group's baseline a window's RMS has to sit before it
# counts as "風切りの酷い窓" rather than ordinary variation (going faster,
# a gust, coasting through a gap in traffic noise).
DEFAULT_WIND_THRESHOLD_DB = 6.0

# Research E-5's own figure: pull a wind-heavy window down by a flat 6 dB.
DEFAULT_WIND_ATTENUATION_DB = -6.0


def _validate_dbfs(value: float, *, label: str = "an RMS level") -> None:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value > 0:
        raise ValueError(f"{label} must not exceed 0 dBFS")


def rms_baseline(rms_values: Sequence[float]) -> float:
    """The shared quiet level a group of windows' engine/wind noise should
    read against.

    The median, not the mean, so one window with wind roaring into the
    microphone does not drag the baseline itself upward and mask its own
    excess -- the same reason app.story_color.luma_target uses the median
    for brightness.
    """
    if not rms_values:
        raise ValueError("need at least one window's RMS level to find a baseline")
    for value in rms_values:
        _validate_dbfs(value)
    return statistics.median(rms_values)


def wind_attenuation_db(
    rms: float,
    baseline: float,
    *,
    threshold_db: float = DEFAULT_WIND_THRESHOLD_DB,
    attenuation_db: float = DEFAULT_WIND_ATTENUATION_DB,
) -> float:
    """The gain (dB, always 0 or negative) to apply so `rms` stops standing
    out against `baseline`.

    Only how far above the baseline a window sits matters -- a window
    quieter than its neighbours is never boosted, because a ride's own
    quiet moments (coasting, waiting at a light) are not a defect to
    correct. A window at or above `baseline + threshold_db` is judged
    wind-heavy and pulled down by the flat `attenuation_db`; anything under
    the threshold is left alone (0.0) rather than nudged proportionally,
    because a few dB of ordinary variation between windows is not the
    "酷い" (severe) case E-5 calls out.
    """
    _validate_dbfs(rms, label="rms")
    _validate_dbfs(baseline, label="baseline")
    if not math.isfinite(threshold_db) or threshold_db <= 0:
        raise ValueError("threshold_db must be a finite positive number")
    if not math.isfinite(attenuation_db) or attenuation_db >= 0:
        raise ValueError("attenuation_db must be a finite negative number")
    if rms - baseline >= threshold_db:
        return attenuation_db
    return 0.0


def wind_attenuations(
    rms_values: Sequence[float],
    *,
    baseline: float | None = None,
    threshold_db: float = DEFAULT_WIND_THRESHOLD_DB,
    attenuation_db: float = DEFAULT_WIND_ATTENUATION_DB,
) -> tuple[float, ...]:
    """`wind_attenuation_db` for every window in `rms_values`, in order.

    `baseline` defaults to `rms_baseline(rms_values)` (the group's own
    median); pass an explicit baseline to judge a group against a level
    that is not itself one of the windows (a chapter's opener, for
    instance).
    """
    if not rms_values:
        raise ValueError("need at least one window's RMS level to correct")
    resolved_baseline = baseline if baseline is not None else rms_baseline(rms_values)
    return tuple(
        wind_attenuation_db(
            value,
            resolved_baseline,
            threshold_db=threshold_db,
            attenuation_db=attenuation_db,
        )
        for value in rms_values
    )
