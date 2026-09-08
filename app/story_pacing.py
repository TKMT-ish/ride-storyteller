"""Give each chapter its share of the film, and each window a length that fits.

Two things the research (docs/research-touring-video-quality-ja.md) is
plain about and the first chapter cut was not. A film is paced by the
length of its shots -- one cut in ten seconds, an average of four to
six, never three alike in a row -- and twelve-second windows laid end to
end are the slowest thing on the screen. And a chapter is a part of the
film, not a label on it: on the real rides the windows fell 1/9/3/7 and
5/1/7/0/1/6 across the chapters, because twenty were chosen for the
whole day and then sorted into whatever chapter they landed in.

So the footage is chosen chapter by chapter, each chapter given the
share of the film that its share of the footage earns, with a floor of
one window for any chapter that has one to give. And before choosing,
every window is given the length it will be held: ten seconds for the
few the model ranked at the top, eight for the rest it ranked, six for
the ones it did not -- so that the selection's target counts screen
time, not window time, and a film of the same length carries more
windows. Three alike in a row are broken up afterwards.

The cut starts where the window starts; a shorter hold shows its first
seconds. Nothing here changes what the model said about any window.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta

from app.analysis_look import WindowLook
from app.fixed_shots import FIXED_SHOT_HOLD_S
from app.gap_chapters import GapCharacter
from app.gemini_selection import JudgedCandidate, select_judged_candidates
from app.ride_chapters import RideChapter
from app.story_hold import (
    LONG_HOLD_RANKS as _LONG_RANGE_RANKS,
)
from app.story_hold import (
    choose_half_by_motion,
    hold_all_from_motion,
    hold_range_for,
    trim_bounds_for_half,
)
from app.story_timeline import TimelineFootage

# Held lengths by how the model placed the window: a few of the best get
# the long hold, the ranked rest the medium, the unranked the short.
LONG_HOLD_S = 10.0
MEDIUM_HOLD_S = 8.0
SHORT_HOLD_S = 6.0
# A chapter's first window carries the chapter's title for up to five
# seconds and must stay clean for a second after (app.story_titles), so
# however calm it is, it holds at least this long.
OPENER_MIN_HOLD_S = 6.0
LONG_HOLD_RANKS = 5
# What the film aims at in footage; the material decides. Five minutes now
# that the fixed shots -- setting off, every stop's arrival, picture and
# departure, the highway's on and off, arriving -- are counted inside it.
DEFAULT_FOOTAGE_TARGET_S = 300.0


class StoryPacingError(ValueError):
    """Raised when the film cannot be paced as asked."""


def hold_for(rank: int | None) -> float:
    """How long a window is held, from where the model ranked it."""
    if rank is None:
        return SHORT_HOLD_S
    if rank <= LONG_HOLD_RANKS:
        return LONG_HOLD_S
    return MEDIUM_HOLD_S


def paced(
    candidates: tuple[JudgedCandidate, ...],
    *,
    ranks: Mapping[str, int] | None,
    motion_aware: bool = False,
    fixed: Collection[str] = (),
) -> tuple[JudgedCandidate, ...]:
    """The same candidates, each with the length it would be held on screen.

    The selection counts screen time toward its target, so it must count
    with the holds the film will use. With looks the film holds by motion
    inside each tier's range (`footage_for`); before the set is chosen the
    motion cannot be placed, so each window is counted at its range's
    middle -- shorter than the fixed holds, so the same target takes more
    windows, which is the point of holding shorter.
    """
    ranked = ranks or {}
    pinned = set(fixed)
    return tuple(
        replace(
            candidate,
            duration_s=min(
                candidate.duration_s,
                FIXED_SHOT_HOLD_S
                if candidate.event_id in pinned
                else _expected_hold(ranked.get(candidate.event_id), motion_aware=motion_aware),
            ),
        )
        for candidate in candidates
    )


def _expected_hold(rank: int | None, *, motion_aware: bool) -> float:
    if not motion_aware:
        return hold_for(rank)
    low, high = hold_range_for(rank)
    return (low + high) / 2


def select_by_chapter(
    candidates: tuple[JudgedCandidate, ...],
    chapters: tuple[RideChapter, ...],
    *,
    ranks: Mapping[str, int] | None = None,
    footage_target_s: float = DEFAULT_FOOTAGE_TARGET_S,
    looks: Mapping[str, WindowLook] | None = None,
    moments: Mapping[str, float] | None = None,
    required: Collection[str] = (),
    parked_allowed: Collection[str] = (),
    requires_analysis: bool = True,
    fixed: Collection[str] | None = None,
) -> tuple[str, ...]:
    """Choose the film's windows chapter by chapter, best first within each.

    A chapter's target is its share of the candidates times the film's
    target, never less than one window where it has one, and never more
    than the chapter can actually spend -- a halt is one place and one
    window, and a chapter thinned out by the look-alike rule cannot fill
    a target sized for one twice as full. What a chapter cannot spend is
    handed on to the chapters that still have room (`reallocate_footage_targets`),
    so a day whose stops and thin legs leave minutes unspent still plays
    them somewhere rather than dropping them. The selection inside a
    chapter is the ordinary one -- scores, the model's ranking, spacing,
    one window per halt -- so nothing about how a window is judged
    changes; only how the film's minutes are shared out does.

    `requires_analysis=False` is Gate 7.2's rank-only ride
    (`app.analysis_tournament`): every candidate's `analysis` is `None`,
    the pacing above is already rank-only (`hold_for` reads a rank, never a
    `VideoAnalysis`), and this only has to stop passing that None down as a
    reason to drop every window (see `select_judged_candidates`).

    `fixed` names the required windows held as fixed shots (a moment, a
    place); the other required windows -- the opening's highlights -- are
    paced like any window. Without it, every required window is fixed.
    """
    if footage_target_s <= 0:
        raise StoryPacingError("the film needs a positive footage target")
    if not chapters:
        raise StoryPacingError("the film needs at least one chapter")
    # A fixed shot is counted at the length it will be held, so that two of
    # them cannot overlap on the ride's clock and the target means what it says.
    held = paced(
        candidates,
        ranks=ranks,
        motion_aware=looks is not None,
        fixed=required if fixed is None else fixed,
    )
    by_id = {c.event_id: c for c in held}
    # The fixed shots of the whole day are in the film before any leg
    # chooses, so a leg's ordinary picks keep clear of the next leg's
    # departure as much as of its own windows.
    pinned = [by_id[e] for e in required if e in by_id]
    # The fixed shots take their time off the top: what the legs share out
    # among their ordinary picks is the rest, so a day with many stops does
    # not run long (day 6 reached seven minutes with nineteen fixed shots).
    pinned_s = sum(c.duration_s for c in pinned)
    allowance = max(footage_target_s - pinned_s, SHORT_HOLD_S * len(chapters))
    # A chapter's own room: a halt only ever earns one window; any other
    # chapter cannot show more than its held candidates already carry.
    legs: dict[int, tuple[JudgedCandidate, ...]] = {}
    for index, chapter in enumerate(chapters):
        inside = tuple(c for c in held if chapter.start_time <= c.start_time < chapter.end_time)
        if inside:
            legs[index] = inside
    if not legs:
        return ()
    allocations = tuple(
        ChapterAllocation(
            chapter_id=str(index),
            weight=len(inside),
            capacity_s=SHORT_HOLD_S
            if chapters[index].character is GapCharacter.HALT
            else sum(c.duration_s for c in inside),
        )
        for index, inside in legs.items()
    )
    targets = reallocate_footage_targets(allocations, allowance, floor_s=SHORT_HOLD_S)

    chosen: list[str] = []
    for index, inside in legs.items():
        wanted = frozenset(required) & {c.event_id for c in inside}
        pinned_here = sum(c.duration_s for c in inside if c.event_id in wanted)
        target = targets[str(index)] + pinned_here
        elsewhere = [c for c in pinned if c.event_id not in wanted] + [by_id[e] for e in chosen]
        selection = select_judged_candidates(
            inside,
            ranks=ranks,
            footage_target_s=target,
            looks=looks,
            moments=moments,
            required=wanted,
            avoid=elsewhere,
            parked_allowed=parked_allowed,
            requires_analysis=requires_analysis,
        )
        chosen.extend(selection.selected_event_ids)
    return tuple(chosen)


def footage_for(
    chosen: tuple[str, ...],
    candidates: tuple[JudgedCandidate, ...],
    *,
    ranks: Mapping[str, int] | None,
    looks: Mapping[str, WindowLook] | None = None,
    openers: Collection[str] = (),
    footage_target_s: float | None = None,
    fixed: Collection[str] = (),
) -> list[TimelineFootage]:
    """The chosen windows as footage, held for their paced length, in ride order.

    The long hold goes to the best fifth of the chosen, by the model's
    rank and then its score; the ranked rest get the medium hold and the
    unranked the short. Three equal holds in a row read as a metronome;
    the middle one is nudged to the neighbouring length so the rhythm
    keeps moving.

    With every chosen window's look, the tiers become ranges and how much
    a window moves places it inside its range (E-2, app.story_hold): a
    calm window in the long tier holds eight seconds, a busy one ten. And
    where the look kept the motion second by second, the cut takes the
    half of the window that moves more, so a twelve-second window judged
    whole shows its better six. A window named in `openers` -- the first
    of its chapter, which carries the chapter's title -- holds at least
    `OPENER_MIN_HOLD_S`. Without looks the fixed holds stand as before.

    A day with little footage runs out of windows before the film reaches
    `footage_target_s`; when it is given and the motion-placed holds fall
    short of it, every hold is raised toward the top of its own range in
    proportion, so a short day is told a little slower rather than cut
    short. No hold leaves its range, and the order by motion is kept.

    A window named in `fixed` is a moment's shot (app.fixed_shots): it is
    held `FIXED_SHOT_HOLD_S` from its own start, so the still seconds
    before the move, or after the stop, are the picture.
    """
    by_id = {c.event_id: c for c in candidates}
    ranked = ranks or {}
    # Standing among the chosen, not among everything the model saw: the
    # long hold goes to the best fifth of what the film shows, so a day
    # whose top-ranked windows were alike or in one halt still has a few.
    standing = sorted(
        chosen,
        key=lambda e: (ranked.get(e, 10_000), -by_id[e].score(), by_id[e].start_time),
    )
    long_holds = max(1, -(-len(standing) // 5))
    tier: dict[str, float] = {}
    for position, event_id in enumerate(standing):
        if position < long_holds:
            tier[event_id] = LONG_HOLD_S
        elif event_id in ranked:
            tier[event_id] = MEDIUM_HOLD_S
        else:
            tier[event_id] = SHORT_HOLD_S
    ordered = sorted((by_id[event_id] for event_id in chosen), key=lambda c: c.start_time)
    seen = looks if looks is not None and all(c.event_id in looks for c in ordered) else None
    if seen is None:
        holds = [min(c.duration_s, tier[c.event_id]) for c in ordered]
        for index in range(1, len(holds) - 1):
            if holds[index - 1] == holds[index] == holds[index + 1]:
                holds[index] = MEDIUM_HOLD_S if holds[index] != MEDIUM_HOLD_S else LONG_HOLD_S
    else:
        # The tier chooses the range; motion, against the other chosen
        # windows, chooses the point in it. The synthetic rank only names
        # the tier: the model's own ranks were spent on `standing` above.
        by_motion = hold_all_from_motion(
            [(c.event_id, _range_rank(tier[c.event_id]), seen[c.event_id].motion) for c in ordered]
        )
        holds = [min(c.duration_s, by_motion[c.event_id]) for c in ordered]
        if footage_target_s is not None:
            holds = _raised_toward_target(ordered, holds, tier, footage_target_s)
    opening = set(openers)
    holds = [
        max(hold, min(c.duration_s, OPENER_MIN_HOLD_S)) if c.event_id in opening else hold
        for c, hold in zip(ordered, holds, strict=True)
    ]

    pinned = set(fixed)
    footage: list[TimelineFootage] = []
    for c, hold in zip(ordered, holds, strict=True):
        offset = 0.0
        series = seen[c.event_id].motion_series if seen is not None else ()
        if c.event_id in pinned:
            hold = min(c.duration_s, FIXED_SHOT_HOLD_S)
            series = ()
        if series:
            half = choose_half_by_motion(series)
            offset, _ = trim_bounds_for_half(c.duration_s, half, half_duration_s=hold)
        begins = c.start_time + timedelta(seconds=offset)
        footage.append(
            TimelineFootage(
                event_id=c.event_id,
                start_time=begins,
                end_time=begins + timedelta(seconds=hold),
                source_offset_s=offset,
            )
        )
    return _without_overlaps(footage)


# A cut shorter than this is a flicker; a window squeezed below it gives way.
MIN_CUT_S = 2.0


def _without_overlaps(footage: list[TimelineFootage]) -> list[TimelineFootage]:
    """No two cuts share a second of the ride: the earlier ends where the next begins.

    The selection keeps windows apart by their expected holds, but a hold
    raised toward the target or a cut moved to its window's busier half
    can still reach into the next window's start -- a stop's picture
    beginning inside the shot of pulling in (days 7 and 8). The earlier
    cut is shortened; one squeezed under `MIN_CUT_S` is dropped.
    """
    ordered = sorted(footage, key=lambda f: f.start_time)
    kept: list[TimelineFootage] = []
    for index, item in enumerate(ordered):
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if following is not None and following.start_time < item.end_time:
            item = TimelineFootage(
                event_id=item.event_id,
                start_time=item.start_time,
                end_time=following.start_time,
                source_offset_s=item.source_offset_s,
            )
            if (item.end_time - item.start_time).total_seconds() < MIN_CUT_S:
                continue
        kept.append(item)
    return kept


def _raised_toward_target(
    ordered: list[JudgedCandidate],
    holds: list[float],
    tier: Mapping[str, float],
    footage_target_s: float,
) -> list[float]:
    """Spend a shortfall against the target on longer holds, each within its range."""
    shortfall = footage_target_s - sum(holds)
    if shortfall <= 0:
        return holds
    tops = [min(c.duration_s, hold_range_for(_range_rank(tier[c.event_id]))[1]) for c in ordered]
    headroom = [max(0.0, top - hold) for top, hold in zip(tops, holds, strict=True)]
    room = sum(headroom)
    if room <= 0:
        return holds
    share = min(1.0, shortfall / room)
    return [hold + share * extra for hold, extra in zip(holds, headroom, strict=True)]


def _range_rank(tier_hold: float) -> int | None:
    """The synthetic rank that names a tier's range in app.story_hold."""
    if tier_hold == LONG_HOLD_S:
        return 1
    if tier_hold == MEDIUM_HOLD_S:
        return _LONG_RANGE_RANKS + 1
    return None


def chapter_openers(
    chosen: Collection[str],
    candidates: tuple[JudgedCandidate, ...],
    chapters: tuple[RideChapter, ...],
) -> frozenset[str]:
    """The first chosen window of each chapter, in ride order: it carries the title."""
    by_id = {c.event_id: c for c in candidates}
    picked = sorted((by_id[e] for e in chosen if e in by_id), key=lambda c: c.start_time)
    openers: set[str] = set()
    for chapter in chapters:
        inside = [c for c in picked if chapter.start_time <= c.start_time < chapter.end_time]
        if inside:
            openers.add(inside[0].event_id)
    return frozenset(openers)


@dataclass(frozen=True)
class ChapterAllocation:
    """One chapter's claim on the footage target, before the target is set.

    ``weight`` is the chapter's share of the day's candidates -- what
    ``select_by_chapter`` already divides the target by. ``capacity_s`` is
    the most footage the chapter could actually put on screen at that
    share: a halt that only ever gets one window, or a chapter whose
    candidates thinned out under the look-alike rule, cannot spend a
    target sized for a chapter twice as full.
    """

    chapter_id: str
    weight: float
    capacity_s: float


def reallocate_footage_targets(
    allocations: tuple[ChapterAllocation, ...],
    footage_target_s: float,
    *,
    floor_s: float = SHORT_HOLD_S,
) -> dict[str, float]:
    """Share the footage target by weight, then pass on what a chapter can't spend.

    ``select_by_chapter`` today gives each chapter ``footage_target_s *
    share``, floored at one window's length, and never looks again: a
    stop that only earns one window, or a chapter whose look-alike windows
    were thinned out, leaves its unspent minutes on the floor instead of
    in the film (a day's worth measured at 220 of a 240 second target).

    This gives every chapter its proportional target first, then hands
    whatever a chapter cannot use -- because ``capacity_s`` says so --
    to the chapters that still have room, in proportion to their own
    weight (evenly, if every weight is zero). Handing more to a chapter
    can itself run past its capacity, so the handing round repeats until
    nothing more will move: either every chapter fits under its cap, or
    the chapters still under their cap have absorbed all there is to
    give. A remainder with nowhere left to go -- every chapter now at its
    capacity -- simply goes unspent, the same as today; this only stops
    it from being thrown away while another chapter could still use it.

    Returns the final target for each chapter, keyed by ``chapter_id``,
    each between zero and its ``capacity_s``. Nothing here chooses a
    window or calls the model; it only decides how many seconds each
    chapter is asked to fill.
    """
    if footage_target_s <= 0:
        raise StoryPacingError("the footage target must be positive")
    if floor_s <= 0:
        raise StoryPacingError("the floor must be positive")
    if not allocations:
        raise StoryPacingError("there must be at least one chapter to allocate to")
    ids = [a.chapter_id for a in allocations]
    if len(set(ids)) != len(ids):
        raise StoryPacingError("each chapter_id must appear once")
    for allocation in allocations:
        if not allocation.chapter_id:
            raise StoryPacingError("chapter_id must not be empty")
        if allocation.weight < 0:
            raise StoryPacingError("weight must not be negative")
        if allocation.capacity_s < 0:
            raise StoryPacingError("capacity_s must not be negative")

    by_id = {a.chapter_id: a for a in allocations}
    weight_sum = sum(a.weight for a in allocations)
    if weight_sum > 0:
        base = {a.chapter_id: footage_target_s * a.weight / weight_sum for a in allocations}
    else:
        base = {a.chapter_id: footage_target_s / len(allocations) for a in allocations}
    target = {chapter_id: max(value, floor_s) for chapter_id, value in base.items()}

    remaining_ids = set(target)
    while True:
        overflow = 0.0
        capped_now = []
        for chapter_id in remaining_ids:
            capacity = by_id[chapter_id].capacity_s
            if target[chapter_id] > capacity:
                overflow += target[chapter_id] - capacity
                target[chapter_id] = capacity
                capped_now.append(chapter_id)
        remaining_ids.difference_update(capped_now)
        if overflow <= 0 or not remaining_ids:
            break
        share_sum = sum(by_id[chapter_id].weight for chapter_id in remaining_ids)
        if share_sum > 0:
            for chapter_id in remaining_ids:
                target[chapter_id] += overflow * by_id[chapter_id].weight / share_sum
        else:
            extra = overflow / len(remaining_ids)
            for chapter_id in remaining_ids:
                target[chapter_id] += extra
    return target
