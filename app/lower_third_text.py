"""Fit chapter text to the lower-third overlay E-4 asks for.

docs/research-touring-video-editing-ja.md §5 (meec-11, frame.io/vimeo-LT):
a lower third lives over moving footage for five seconds, not centre-screen
for six with nothing else on the frame, so it earns much less room and much
less time to be read. The research measured today's body text against that
budget and found it wanting -- "出発から3時間06分 · 142.0km · 海抜815m → 67m"
runs about thirty characters, well past what a viewer can read in five
seconds -- and proposed a title of at most twelve characters and a body of
at most twenty-one (§5.1's "6秒に約21字"), one line each.

This module is only the fitting function E-4 needs before any card can move
onto video: given a title and a body's parts ordered from most to least
essential, produce text that always obeys both limits. It drops the least
essential parts before it ever cuts a word in half, and it never invents
new words -- the words themselves still come from app.ride_chapters.

Nothing here reads a path, an asset id, a filename, a coordinate, or a
clock time; it only reshapes strings its caller already built.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

# §5.1's "6秒に約21字" (about 21 characters read in 6 seconds) and the
# research's own title budget (§5.3, "題は12字以内"). Both are counted in
# full-width characters: a Latin letter, a digit or a space takes half the
# room of a kanji, so "Ashton → Karāwera" is nine, not seventeen.
MAX_TITLE_CHARS = 12
MAX_BODY_CHARS = 21

_ELLIPSIS = "…"
# The ellipsis is counted as one full-width character however a font sets it.
_ELLIPSIS_WIDTH = 1.0
_SEPARATOR = " · "
# app.ride_chapters joins a card's body from its parts with this; splitting on
# it gives the parts back, most essential first, for fitting.
BODY_SEPARATOR = _SEPARATOR


def display_width(text: str) -> float:
    """How much room the text takes, in full-width characters."""
    return sum(1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.5 for ch in text)


class LowerThirdTextError(ValueError):
    """Raised when there is no text left to put on the overlay."""


@dataclass(frozen=True)
class LowerThirdText:
    """Title and body already fitted to the overlay's two limits.

    The invariant is enforced here, not just by the functions below, so that
    a caller who builds one directly (in a test, or from a cached value)
    cannot smuggle in text the overlay would have to truncate itself.
    """

    title: str
    body: str

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.body.strip():
            raise LowerThirdTextError("a lower third needs a title and a body")
        if display_width(self.title) > MAX_TITLE_CHARS:
            raise LowerThirdTextError(f"title exceeds {MAX_TITLE_CHARS} characters: {self.title!r}")
        if display_width(self.body) > MAX_BODY_CHARS:
            raise LowerThirdTextError(f"body exceeds {MAX_BODY_CHARS} characters: {self.body!r}")


def fit_title(title: str, *, max_chars: int = MAX_TITLE_CHARS) -> str:
    """Shorten a title to max_chars, cutting at the end with an ellipsis.

    A title already inside the limit is returned stripped and otherwise
    untouched -- fitting is not an excuse to reword what app.ride_chapters
    already chose.
    """
    if max_chars <= 0:
        raise LowerThirdTextError("max_chars must be positive")
    stripped = title.strip()
    if display_width(stripped) <= max_chars:
        return stripped
    if max_chars <= _ELLIPSIS_WIDTH:
        return _take(stripped, max_chars)
    return _take(stripped, max_chars - _ELLIPSIS_WIDTH).rstrip() + _ELLIPSIS


def _take(text: str, width: float) -> str:
    """The longest prefix that fits in `width` full-width characters."""
    kept: list[str] = []
    used = 0.0
    for ch in text:
        used += display_width(ch)
        if used > width:
            break
        kept.append(ch)
    return "".join(kept)


def fit_body(
    parts: Sequence[str],
    *,
    max_chars: int = MAX_BODY_CHARS,
    separator: str = _SEPARATOR,
) -> str:
    """Join parts most-essential-first, dropping the least essential first.

    ``parts`` must already be ordered from most to least essential: the
    first part is never dropped, so the result always says at least that
    much. Parts are dropped from the end, one at a time, until the joined
    text fits; if even the first part alone still overruns the limit once
    joined with nothing, it is truncated the way fit_title truncates a
    title, never cut mid-word beyond what an ellipsis demands.
    """
    non_empty = [part.strip() for part in parts if part is not None and part.strip()]
    if not non_empty:
        raise LowerThirdTextError("fit_body needs at least one non-empty part")
    kept = list(non_empty)
    while display_width(separator.join(kept)) > max_chars and len(kept) > 1:
        kept.pop()
    joined = separator.join(kept)
    if display_width(joined) <= max_chars:
        return joined
    return fit_title(kept[0], max_chars=max_chars)


def fit_lower_third_text(
    title: str,
    body_parts: Sequence[str],
    *,
    max_title_chars: int = MAX_TITLE_CHARS,
    max_body_chars: int = MAX_BODY_CHARS,
) -> LowerThirdText:
    """Fit a chapter's title and ordered body parts to the overlay's limits."""
    return LowerThirdText(
        title=fit_title(title, max_chars=max_title_chars),
        body=fit_body(body_parts, max_chars=max_body_chars),
    )
