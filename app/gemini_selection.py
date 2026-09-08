"""Turn what Gemini saw into which clips the film uses.

This is the join the product was missing. GPS narrows a ride to candidate
windows cheaply, and `app.analysis_proxy` makes copies small enough to send,
but until something reads the judgement back and acts on it, the model is
looking at footage nobody listens to. This decides.

Two scores come back for each candidate and they answer different questions.
`visual_interest_score` asks whether a moment is worth watching;
`story_relevance_score` asks whether it earns its place in this ride's story.
A striking clip of a car park is high on the first and low on the second, and
a film made from the first alone is a showreel rather than a journey. They are
combined with weights that are stated and adjustable rather than buried.

`confidence` is not another score to average in. A confident middling verdict
is worth more than an unsure glowing one, so low confidence excludes a
candidate outright rather than being blended away.

Selection is greedy by score but spaced in ride time. Five clips from one
good minute would make a film about that minute, and the ride continued.

Spacing in time is not enough where the ride stopped. On the real second
day the rider spent twenty minutes in a museum with the camera running,
the model gave those windows the day's highest story scores -- a landmark,
a stop -- and the film showed five of them in a row, a full minute of a
five-minute film. Each was two minutes from the last, so the spacing rule
was satisfied and the film was still about the museum. A place the ride
halted at is one place, however long it stayed, and one place gets one
window. The caller says which windows share a halt; it is read off the
GPS track, and the model's scores are not touched.

Every decision carries a fixed reason code, so a candidate's fate can be
explained without quoting the model or exposing an identifier.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.analysis_look import LOOK_ALIKE, WindowLook
from app.contracts import VideoAnalysis
from app.gps.turns import SharpTurn
from app.rider_in_frame import rider_fills_the_frame
from app.stop_kinds import at_a_private_residence

GEMINI_SELECTION_SCHEMA_VERSION = "gemini-selection-v1"

# A moment can be beautiful and still not belong in this ride's story. The
# story weight leads for that reason; both are adjustable.
DEFAULT_INTEREST_WEIGHT = 0.4
DEFAULT_STORY_WEIGHT = 0.6

# Below this the model is guessing, and a guess should not reach the film.
DEFAULT_MINIMUM_CONFIDENCE = 0.4
# Below this the model looked and did not think much of it.
DEFAULT_MINIMUM_SCORE = 0.35
# Clips closer together than this describe the same stretch of road.
DEFAULT_MINIMUM_SEPARATION_S = 120.0
# What the film is aiming at. Elastic: the material decides the real length.
DEFAULT_FOOTAGE_TARGET_S = 240.0
# A place the ride halted at is shown this many times, however long it
# stayed and however well the model liked what it saw there.
DEFAULT_MAX_WINDOWS_PER_HALT = 1
# Scores this close apart are the same judgement, not a ranking. On the first
# real ride 30 windows scored exactly 0.66 and 33 scored exactly 0.54; the
# model was not telling them apart, so nothing here should pretend it did.
DEFAULT_TIE_EPSILON = 0.02

# Coarse families for the model's free-text road label, used only to break
# ties between windows the model scored alike. First match wins, so the more
# specific words come first. This never touches a score: it decides which of
# two windows the model rated equally gets to speak for its stretch, and it
# prefers the one that shows a kind of road the film has not shown yet.
ROAD_FAMILIES: tuple[tuple[str, str], ...] = (
    ("parking", "parking"),
    ("intersection", "junction"),
    ("roundabout", "junction"),
    ("highway", "highway"),
    ("arterial", "highway"),
    ("multi-lane", "highway"),
    ("street", "street"),
    ("suburban", "street"),
    ("urban", "street"),
    ("mountain", "rural"),
    ("rural", "rural"),
    ("country", "rural"),
    ("two-lane", "rural"),
)

# Fixed, non-identifying vocabulary.
REASON_SELECTED = "selected"
# Kept because the track proves it is a moment of the day -- departure,
# a halt's two ends, arrival -- whatever it scored (app.fixed_shots).
REASON_FIXED_SHOT = "moment_the_track_proves"
REASON_NO_ANALYSIS = "not_analysed"
REASON_RIDER_IN_FRAME = "rider_fills_the_frame"
REASON_PRIVATE_RESIDENCE = "at_a_private_residence"
REASON_STANDING = "bike_standing_still"
REASON_LOW_CONFIDENCE = "confidence_below_floor"
REASON_LOW_SCORE = "score_below_floor"
REASON_TOO_CLOSE = "too_close_to_a_stronger_clip"
REASON_SAME_HALT = "same_halt_already_shown"
REASON_LOOKS_ALIKE = "looks_like_the_window_before_it"
REASON_ENOUGH_FOOTAGE = "film_already_long_enough"


class GeminiSelectionError(ValueError):
    """Raised when a selection cannot be made from what was given."""


@dataclass(frozen=True)
class JudgedCandidate:
    """One candidate window and what the model made of it."""

    event_id: str
    start_time: datetime
    duration_s: float
    analysis: VideoAnalysis | None
    # Which halt this window is part of, when the ride was stopped here;
    # None on the move. Windows with the same number are the same place.
    halt: int | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("a judged candidate needs its event")
        if self.start_time.tzinfo is None:
            raise ValueError("a judged candidate needs a timezone-aware start")
        if self.duration_s <= 0:
            raise ValueError("a judged candidate must cover a positive duration")

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(seconds=self.duration_s)

    def score(
        self,
        *,
        interest_weight: float = DEFAULT_INTEREST_WEIGHT,
        story_weight: float = DEFAULT_STORY_WEIGHT,
    ) -> float:
        """How much this candidate is worth, by the stated weighting."""
        if self.analysis is None:
            return 0.0
        total = interest_weight + story_weight
        if total <= 0:
            raise GeminiSelectionError("the weights must add up to something")
        return (
            self.analysis.visual_interest_score * interest_weight
            + self.analysis.story_relevance_score * story_weight
        ) / total


@dataclass(frozen=True)
class SelectionVerdict:
    """What became of one candidate, and why, without naming the model."""

    event_id: str
    selected: bool
    reason: str
    score: float

    def to_dict(self) -> dict[str, object]:
        """Safe view: no event ID, description, or model text."""
        return {
            "selected": self.selected,
            "reason": self.reason,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class GeminiSelection:
    """Every candidate's fate, and the footage the film ended up with."""

    verdicts: tuple[SelectionVerdict, ...]
    footage_duration_s: float

    @property
    def selected_event_ids(self) -> tuple[str, ...]:
        return tuple(v.event_id for v in self.verdicts if v.selected)

    def to_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for verdict in self.verdicts:
            counts[verdict.reason] = counts.get(verdict.reason, 0) + 1
        return {
            "schema_version": GEMINI_SELECTION_SCHEMA_VERSION,
            "candidate_count": len(self.verdicts),
            "selected_count": len(self.selected_event_ids),
            "footage_duration_s": round(self.footage_duration_s, 3),
            "reasons": counts,
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
        }


def road_family(road_type: str) -> str:
    """The coarse kind of road a label describes, for telling clips apart."""
    text = " ".join(road_type.lower().split())
    for needle, family in ROAD_FAMILIES:
        if needle in text:
            return family
    return text or "unknown"


def select_judged_candidates(
    candidates: tuple[JudgedCandidate, ...],
    *,
    interest_weight: float = DEFAULT_INTEREST_WEIGHT,
    story_weight: float = DEFAULT_STORY_WEIGHT,
    minimum_confidence: float = DEFAULT_MINIMUM_CONFIDENCE,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    minimum_separation_s: float = DEFAULT_MINIMUM_SEPARATION_S,
    footage_target_s: float = DEFAULT_FOOTAGE_TARGET_S,
    tie_epsilon: float = DEFAULT_TIE_EPSILON,
    ranks: Mapping[str, int] | None = None,
    max_windows_per_halt: int = DEFAULT_MAX_WINDOWS_PER_HALT,
    looks: Mapping[str, WindowLook] | None = None,
    look_alike: float = LOOK_ALIKE,
    moments: Mapping[str, float] | None = None,
    required: Collection[str] = (),
    avoid: Sequence[JudgedCandidate] = (),
    parked_allowed: Collection[str] = (),
    requires_analysis: bool = True,
) -> GeminiSelection:
    """Choose the clips the film uses, and say why for every candidate.

    Candidates are taken best-first, but a candidate too close in ride time
    to one already taken is left out: the stronger clip already speaks for
    that stretch. Selection stops once there is enough footage, which is a
    target rather than a quota -- nothing is padded to reach it, and a ride
    that cannot fill it simply makes a shorter film.

    Best-first has to say what happens when the model rated many windows
    the same, and on the first real ride it rated most of them the same:
    scores sat at 0.66 or 0.54 for a third of the windows each. Taking ties
    in ride order filled the film with the first highway the camera saw --
    ten of twenty clips carried the label "highway" outright. So among
    windows the model scored alike, the one taken is the one that shows a
    kind of road the film has not shown yet, and failing that, the one
    farthest from anything already taken. The model's ranking is untouched;
    this only decides what it declined to decide.

    `moments` names the windows the track proves hold a moment (a sharp turn,
    app.gps.turns) with its size; among windows scored alike, those go first.

    `required` names the windows the film always carries -- the fixed shots
    of setting off, stopping and arriving (app.fixed_shots). They are taken
    first, before any score is compared, and the score and confidence
    floors do not apply to them, nor the rider rule (the moment matters
    more; the fan of candidate windows prefers a clean one where it can);
    a window the model never judged is still out.

    `parked_allowed` names the windows that may show a car park -- the
    day's own departure and arrival -- where every other one the model
    placed in a car park, a forecourt or a driveway is out (point 9).

    `avoid` are windows already in the film from outside this set -- the
    neighbouring legs' picks and their fixed shots. They count for the
    separation, not for the footage: a window too close to one of them is
    out, so two legs never show the same minute twice, and a window never
    overlaps one across a leg's boundary.

    `requires_analysis` is the switch for Gate 7.2's rank-only path
    (`app.analysis_tournament`): a comparison never describes a window, so
    there is no `VideoAnalysis` to read a floor from. With it False, a
    candidate with `analysis=None` is not excluded on that account alone --
    every check that reads `.analysis` (the rider filling the frame, a car
    park, standing still, the confidence and score floors, the road-family
    tie-break) can only act on what it is given, so none of them fire, and
    the choice among ties falls straight through to `ranks`, which a
    tournament always supplies for every candidate it ranked. This is a
    coarser film -- nothing here stops a rider-filling-the-frame window a
    comparison never flagged -- and that trade is Gate 7.2's, made once
    here rather than guessed at by each caller.
    """
    if minimum_separation_s < 0:
        raise GeminiSelectionError("a separation cannot be negative")
    if footage_target_s <= 0:
        raise GeminiSelectionError("the film needs a positive footage target")
    if not candidates:
        raise GeminiSelectionError("there are no candidates to choose from")

    event_ids = [candidate.event_id for candidate in candidates]
    if len(event_ids) != len(set(event_ids)):
        raise GeminiSelectionError("a candidate list must not repeat one event")

    if tie_epsilon < 0:
        raise GeminiSelectionError("a tie margin cannot be negative")
    if max_windows_per_halt < 1:
        raise GeminiSelectionError("a halt is shown at least once or the rule is a ban")
    if look_alike < 0:
        raise GeminiSelectionError("a look-alike distance cannot be negative")

    scores = {
        candidate.event_id: candidate.score(
            interest_weight=interest_weight, story_weight=story_weight
        )
        for candidate in candidates
    }
    verdicts: dict[str, SelectionVerdict] = {}

    def settle(candidate: JudgedCandidate, reason: str) -> None:
        verdicts[candidate.event_id] = SelectionVerdict(
            event_id=candidate.event_id,
            selected=reason in (REASON_SELECTED, REASON_FIXED_SHOT),
            reason=reason,
            score=scores[candidate.event_id],
        )

    # The floors are about the candidate alone, so they are settled first.
    wanted = set(required)
    may_park = set(parked_allowed)
    pool: list[JudgedCandidate] = []
    for candidate in candidates:
        reason = _floor_reason(
            candidate,
            scores[candidate.event_id],
            minimum_confidence=minimum_confidence,
            minimum_score=minimum_score,
            requires_analysis=requires_analysis,
        )
        if (
            reason in (None, REASON_LOW_CONFIDENCE, REASON_LOW_SCORE, REASON_RIDER_IN_FRAME)
            and candidate.analysis is not None
            and at_a_private_residence(candidate.analysis)
        ):
            # The owner's correction (2026-09-07): a car park is fine, a
            # scene that could say whose house this is never is -- not
            # even for a fixed shot.
            reason = REASON_PRIVATE_RESIDENCE
        if (
            reason is None
            and candidate.event_id not in may_park
            and candidate.analysis is not None
            and candidate.analysis.stationary == "yes"
        ):
            # The model says the bike never moved in this window: waiting at
            # a light, parked. Not the ride (the owner's day-1 note).
            reason = REASON_STANDING
        if candidate.event_id in wanted and reason in (
            REASON_LOW_CONFIDENCE,
            REASON_LOW_SCORE,
            REASON_RIDER_IN_FRAME,
        ):
            # A fixed shot is the moment itself; the owner (2026-09-07) keeps
            # it even with the rider in the mirror. `choose_shots` prefers a
            # moving, rider-free window where the fan offers one.
            reason = None
        if reason is None:
            pool.append(candidate)
        else:
            settle(candidate, reason)

    taken: list[JudgedCandidate] = []
    footage_s = 0.0
    # The fixed shots first, in ride order: they are not competing -- but
    # two of them cannot share the same seconds of the ride (a stop's own
    # picture beginning inside the shot of pulling into it).
    for candidate in sorted((c for c in pool if c.event_id in wanted), key=lambda c: c.start_time):
        pool.remove(candidate)
        if any(_separation_s(candidate, already) <= 0.0 for already in (*taken, *avoid)):
            settle(candidate, REASON_TOO_CLOSE)
            continue
        taken.append(candidate)
        footage_s += candidate.duration_s
        settle(candidate, REASON_FIXED_SHOT)
    while pool:
        if footage_s >= footage_target_s:
            for candidate in pool:
                settle(candidate, REASON_ENOUGH_FOOTAGE)
            break
        best = max(scores[candidate.event_id] for candidate in pool)
        tied = [c for c in pool if scores[c.event_id] >= best - tie_epsilon]
        ranked = ranks or {}
        proven = moments or {}
        # Among windows the model scored alike, one the track proves holds a
        # moment -- a corner the rider felt -- goes first (Q1); then the
        # model's own comparison decides.
        pick = min(
            tied,
            key=lambda c: (
                0 if c.event_id in proven else 1,
                ranked.get(c.event_id, len(ranked) + 1),
                _family_repeats(c, taken),
                -_nearest_taken_s(c, taken),
                c.start_time,
            ),
        )
        pool.remove(pick)
        if any(
            _separation_s(pick, already) < minimum_separation_s
            for already in (*taken, *avoid)
            if already.event_id != pick.event_id
        ):
            settle(pick, REASON_TOO_CLOSE)
            continue
        if pick.halt is not None and (
            sum(1 for already in taken if already.halt == pick.halt) >= max_windows_per_halt
        ):
            settle(pick, REASON_SAME_HALT)
            continue
        if looks is not None and _looks_like_a_neighbour(pick, taken, looks, look_alike):
            settle(pick, REASON_LOOKS_ALIKE)
            continue
        taken.append(pick)
        footage_s += pick.duration_s
        settle(pick, REASON_SELECTED)

    # Report in ride order, because that is the order a reader thinks in.
    ordered = sorted(candidates, key=lambda candidate: candidate.start_time)
    return GeminiSelection(
        verdicts=tuple(verdicts[candidate.event_id] for candidate in ordered),
        footage_duration_s=footage_s,
    )


def clears_the_floor(
    candidate: JudgedCandidate,
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_CONFIDENCE,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
) -> bool:
    """Whether this window would enter the film on its own account.

    The opening's highlights are chosen before the selection runs, so they
    have to answer the same question the selection would ask: a judgement
    that likes nothing must still stop the film, not open it.
    """
    return (
        _floor_reason(
            candidate,
            candidate.score(),
            minimum_confidence=minimum_confidence,
            minimum_score=minimum_score,
        )
        is None
    )


def _floor_reason(
    candidate: JudgedCandidate,
    score: float,
    *,
    minimum_confidence: float,
    minimum_score: float,
    requires_analysis: bool = True,
) -> str | None:
    """Why this candidate is out on its own account, or None if it is not."""
    if candidate.analysis is None:
        # A rank-only ride (Gate 7.2) never buys one; there is nothing here
        # to exclude it for, so it goes on to compete on its rank alone.
        return None if not requires_analysis else REASON_NO_ANALYSIS
    if rider_fills_the_frame(candidate.analysis):
        # The owner's rule (2026-09-06): a window where the rider, not the
        # road, is the picture is out however well the model liked it.
        return REASON_RIDER_IN_FRAME
    if candidate.analysis.confidence < minimum_confidence:
        # An unsure verdict is not a quiet negative; it is no verdict at all.
        return REASON_LOW_CONFIDENCE
    if score < minimum_score:
        return REASON_LOW_SCORE
    return None


def _looks_like_a_neighbour(
    candidate: JudgedCandidate,
    taken: list[JudgedCandidate],
    looks: Mapping[str, WindowLook],
    look_alike: float,
) -> bool:
    """Whether the film would show the same picture just before or after this."""
    own = looks.get(candidate.event_id)
    if own is None or not taken:
        return False
    before = [c for c in taken if c.start_time < candidate.start_time]
    after = [c for c in taken if c.start_time > candidate.start_time]
    neighbours = []
    if before:
        neighbours.append(max(before, key=lambda c: c.start_time))
    if after:
        neighbours.append(min(after, key=lambda c: c.start_time))
    for neighbour in neighbours:
        other = looks.get(neighbour.event_id)
        if other is not None and own.distance(other) < look_alike:
            return True
    return False


def _family_repeats(candidate: JudgedCandidate, taken: list[JudgedCandidate]) -> int:
    """How many clips already taken show the same kind of road."""
    if candidate.analysis is None:
        return 0
    family = road_family(candidate.analysis.road_type)
    return sum(
        1
        for already in taken
        if already.analysis is not None and road_family(already.analysis.road_type) == family
    )


def _nearest_taken_s(candidate: JudgedCandidate, taken: list[JudgedCandidate]) -> float:
    """Ride time to the closest clip already taken; zero when none is."""
    if not taken:
        return 0.0
    return min(_separation_s(candidate, already) for already in taken)


def _separation_s(left: JudgedCandidate, right: JudgedCandidate) -> float:
    """The gap between two windows, or zero where they overlap."""
    if left.start_time >= right.end_time:
        return (left.start_time - right.end_time).total_seconds()
    if right.start_time >= left.end_time:
        return (right.start_time - left.end_time).total_seconds()
    return 0.0


def window_moments(
    candidates: Sequence[JudgedCandidate], turns: Sequence[SharpTurn]
) -> dict[str, float]:
    """Which windows hold a sharp turn, and how sharp: the middle of the turn inside the window."""
    moments: dict[str, float] = {}
    for candidate in candidates:
        sharpest = max(
            (
                abs(t.degrees)
                for t in turns
                if candidate.start_time <= t.middle <= candidate.end_time
            ),
            default=0.0,
        )
        if sharpest > 0:
            moments[candidate.event_id] = sharpest
    return moments
