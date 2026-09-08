"""Add up climbing and descent without adding up the barometer's jitter.

A consumer GPS track wobbles by a few metres from point to point on flat
ground, and summing every wobble as a climb turns a day with 3,000 m of
real ascent into 5,400. The sum is honest arithmetic on dishonest data,
and the cards were printing it.

The usual remedy is hysteresis: a change of height counts only once it
has run past a threshold from the last counted turning point. Small
oscillations never reach it and vanish; a real climb runs through it and
is counted in full. Ten metres is comfortably above the wobble of the
tracks seen so far and below any climb worth a word on a card.
"""

from __future__ import annotations

from collections.abc import Iterable

# The barometer's wobble on flat ground is a few metres; a real rise is more.
DEFAULT_HYSTERESIS_M = 10.0


def gain_and_loss(
    heights: Iterable[float | None], *, hysteresis_m: float = DEFAULT_HYSTERESIS_M
) -> tuple[float, float]:
    """Metres climbed and descended, counting only moves past the hysteresis."""
    if hysteresis_m < 0:
        raise ValueError("hysteresis cannot be negative")
    gain = 0.0
    loss = 0.0
    anchor: float | None = None
    for height in heights:
        if height is None:
            continue
        if anchor is None:
            anchor = height
            continue
        delta = height - anchor
        if delta >= hysteresis_m:
            gain += delta
            anchor = height
        elif -delta >= hysteresis_m:
            loss += -delta
            anchor = height
    return gain, loss
