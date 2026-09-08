"""The opening's highlights: the frames a photographer would keep, four of them, one second each.

The owner's day-1 note (2026-09-07) and the research behind it
(docs/research-touring-video-editing-ja.md §10): the first seconds decide
whether anyone keeps watching, and what holds them is not the window that
moves most but the picture that looks best -- a view opening up, a
coastline, a town street, a stop with a view. So the picker ranks windows
by the model's `photogenic_score` (its `visual_interest_score` and scenery
words where the older record has none), keeps the subjects distinct, spreads
the four across the day, and shows them in ride order. The rider's mirror
never opens a film, nor a room, nor anyone's driveway; a stop with a view
may, after every moving picture has had its turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.gemini_selection import JudgedCandidate
from app.rider_in_frame import rider_fills_the_frame
from app.stop_kinds import at_a_private_residence, indoors

HIGHLIGHT_COUNT = 4
HIGHLIGHT_S = 1.0
# Two highlights come no closer than this on the ride's clock.
HIGHLIGHT_SPREAD_S = 20 * 60.0
# Below this a window is not a picture, whatever else it is.
MIN_PHOTOGENIC = 0.55
# Words the older records use for pictures worth keeping, with how much they say.
_SCENIC_WORDS: tuple[tuple[str, float], ...] = (
    ("mountain", 0.25),
    ("coast", 0.25),
    ("sea", 0.2),
    ("ocean", 0.2),
    ("lake", 0.25),
    ("river", 0.15),
    ("valley", 0.2),
    ("gorge", 0.2),
    ("vista", 0.25),
    ("panoram", 0.25),
    ("skyline", 0.25),
    ("city", 0.15),
    ("harbour", 0.2),
    ("harbor", 0.2),
    ("bridge", 0.15),
    ("snow", 0.2),
    ("sunset", 0.25),
    ("sunrise", 0.25),
    ("glacier", 0.3),
    ("volcan", 0.25),
)
_DULL_WORDS: tuple[str, ...] = ("traffic", "queue", "car park", "parking", "intersection")
# Words the older records use when the bike stood still through the window.
_STILL_WORDS: tuple[str, ...] = ("stationary", "static view", "static shot", "parked", "stopped")
# A picture taken standing still opens the film only when it is of one of these.
_STILL_SUBJECTS: frozenset[str] = frozenset(
    {"vista", "mountains", "water", "landmark", "cityscape", "rest_stop"}
)


@dataclass(frozen=True)
class Highlight:
    event_id: str
    start_time: datetime
    subject: str
    score: float
    moving: bool = True


def moving(candidate: JudgedCandidate) -> bool:
    """Whether the bike rode in the window: the model's answer, else its words."""
    analysis = candidate.analysis
    if analysis is None:
        return True
    if analysis.stationary in ("yes", "no"):
        return analysis.stationary == "no"
    text = analysis.visual_description.lower()
    return not any(word in text for word in _STILL_WORDS)


def photogenic(candidate: JudgedCandidate) -> float | None:
    """How much of a picture the window is, from the model's answer or its words."""
    analysis = candidate.analysis
    if analysis is None:
        return None
    if analysis.photogenic_score is not None:
        return analysis.photogenic_score
    text = " ".join(
        (analysis.visual_description, " ".join(analysis.scenery_tags), analysis.road_type)
    ).lower()
    bonus = max((weight for word, weight in _SCENIC_WORDS if word in text), default=0.0)
    penalty = 0.15 if any(word in text for word in _DULL_WORDS) else 0.0
    return max(0.0, min(1.0, 0.75 * analysis.visual_interest_score + bonus - penalty))


def subject_of(candidate: JudgedCandidate) -> str:
    """The picture's subject, from the model's answer or its words."""
    analysis = candidate.analysis
    if analysis is None:
        return "none"
    if analysis.highlight_subject not in ("unknown", "none"):
        return analysis.highlight_subject
    text = f"{analysis.visual_description} {' '.join(analysis.scenery_tags)}".lower()
    for words, subject in (
        (("mountain", "snow", "glacier", "volcan", "alpine"), "mountains"),
        (("coast", "sea", "ocean", "lake", "river", "harbour", "harbor", "beach"), "water"),
        (("city", "skyline", "town", "street", "urban"), "cityscape"),
        (("bridge", "monument", "tower", "landmark"), "landmark"),
        (("winding", "curve", "hairpin", "bend"), "winding_road"),
        (("sunset", "sunrise", "cloud", "storm", "rainbow"), "sky"),
        (("valley", "vista", "panoram", "view", "plain", "farmland"), "vista"),
    ):
        if any(word in text for word in words):
            return subject
    return "none"


def pick_highlights(
    candidates: Sequence[JudgedCandidate],
    *,
    ride_start: datetime,
    ride_end: datetime,
    count: int = HIGHLIGHT_COUNT,
    spread_s: float = HIGHLIGHT_SPREAD_S,
    minimum: float = MIN_PHOTOGENIC,
    scores: Mapping[str, float] | None = None,
) -> tuple[Highlight, ...]:
    """The best pictures of the day, distinct in subject, spread out, in ride order.

    Best-first by the photogenic score (ties by the window's own score);
    a subject already taken loses to the next best of another subject
    until every subject is used once; two picks keep `spread_s` apart.
    Windows the rider fills, windows indoors, and windows that could
    identify a home are out. The bike moving comes first (the owner,
    2026-09-07: a deck at a lookout is not a riding film's opening): a
    picture taken standing still is taken only when nothing moving is
    left, and only of a view, a landmark, a town or a stop with a view.
    """
    if count < 0 or spread_s < 0:
        raise ValueError("the highlight count and spread must not be negative")
    pool: list[Highlight] = []
    for candidate in candidates:
        analysis = candidate.analysis
        if analysis is None or rider_fills_the_frame(analysis):
            continue
        if indoors(analysis) or at_a_private_residence(analysis):
            continue
        picture = photogenic(candidate)
        if picture is None:
            continue
        if not ride_start <= candidate.start_time <= ride_end:
            continue
        tie = (scores or {}).get(candidate.event_id, candidate.score())
        pool.append(
            Highlight(
                candidate.event_id,
                candidate.start_time,
                subject_of(candidate),
                picture + 0.01 * tie,
                moving=moving(candidate),
            )
        )
    pool.sort(key=lambda h: (-h.score, h.start_time))
    chosen: list[Highlight] = []
    gap = timedelta(seconds=spread_s)
    # Moving pictures: one of each subject, then any subject, then a plain
    # day's best windows. Standing pictures of a view only after that.
    for pass_number in (0, 1, 2, 3):
        for highlight in pool:
            if len(chosen) >= count or highlight in chosen:
                continue
            if pass_number < 3 and not highlight.moving:
                continue
            if pass_number == 3 and (highlight.moving or highlight.subject not in _STILL_SUBJECTS):
                continue
            if pass_number != 2 and highlight.score < minimum:
                continue
            if any(abs(highlight.start_time - c.start_time) < gap for c in chosen):
                continue
            if pass_number == 0 and any(c.subject == highlight.subject for c in chosen):
                continue
            chosen.append(highlight)
    return tuple(sorted(chosen, key=lambda h: h.start_time))
