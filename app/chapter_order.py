"""Order the windows inside one chapter so no three run the same way.

docs/research-touring-video-editing-ja.md §2.2 (E-1) reads the current
selection as "one window at a time" -- windows are ranked and picked, but
never placed against their neighbours. The research names three rules for
what a chapter's own order should do once its windows are chosen:

1. The chapter's first window is its "opener" -- not necessarily the
   highest-ranked one, but whichever one best shows the chapter's own
   character (the research's example: a "long descent" chapter opens on
   a window that is descending).
2. The rest alternate by how much the picture moves ("動きの量の大小を
   交互に") -- three windows of alike motion in a row read as one flat
   shot held too long, even when they are three different clips.
3. The chapter's last window runs long, for the "breath" a chapter takes
   before it ends (E4 in the same research).

This module is only the first two: given which window (if any) opens the
chapter and each window's motion reading (app.analysis_look.WindowLook.
motion, already measured off the 1fps judgement proxy), it returns the
play order. Rule 3 is a hold-length decision app.story_hold already owns
(the tier a window's hold sits in), not an ordering one, so it is left
there. Wiring this order into which footage a chapter actually plays is
a rendering-facing choice for whoever next assembles a chapter's beats,
not something a code-only change should switch on by itself.

Nothing here reads a path, an asset id, or a chapter's title text --
only the motion numbers app.analysis_look already produced and the
window ids the caller already has.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


class ChapterOrderError(ValueError):
    """Raised when a chapter's windows cannot be ordered."""


@dataclass(frozen=True)
class ChapterWindow:
    """One window competing for a spot in a chapter's order."""

    window_id: str
    motion: float
    opens_chapter: bool = False

    def __post_init__(self) -> None:
        if not self.window_id:
            raise ChapterOrderError("a window needs a non-empty id")
        if not math.isfinite(self.motion) or self.motion < 0:
            raise ChapterOrderError("motion is a non-negative frame-difference reading")


def order_chapter_windows(windows: Sequence[ChapterWindow]) -> tuple[str, ...]:
    """The play order for one chapter's windows.

    The opener (at most one window may set ``opens_chapter``) always
    plays first. Every other window is sorted by motion and dealt out
    alternately from the most-motion end and the least-motion end, so
    the play order goes high, low, high, low, ... and a run of three
    alike in how much they move never happens. Ties in motion break on
    ``window_id`` so the order is deterministic.
    """
    if not windows:
        raise ChapterOrderError("a chapter needs at least one window")
    ids = [window.window_id for window in windows]
    if len(set(ids)) != len(ids):
        raise ChapterOrderError("window ids must be unique within a chapter")
    openers = [window for window in windows if window.opens_chapter]
    if len(openers) > 1:
        raise ChapterOrderError("at most one window can open a chapter")
    opener = openers[0] if openers else None
    rest = [window for window in windows if window is not opener]

    by_motion = sorted(rest, key=lambda window: (-window.motion, window.window_id))
    zigzag: list[ChapterWindow] = []
    low, high = 0, len(by_motion) - 1
    take_from_top = True
    while low <= high:
        if take_from_top:
            zigzag.append(by_motion[low])
            low += 1
        else:
            zigzag.append(by_motion[high])
            high -= 1
        take_from_top = not take_from_top

    ordered = ([opener] if opener is not None else []) + zigzag
    return tuple(window.window_id for window in ordered)
