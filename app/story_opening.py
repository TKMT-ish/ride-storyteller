"""Open the film on its best moment, and close it on the day's account.

A touring film that opens with a title card and the first minutes of
road loses its viewer before the ride has begun; the research behind
docs/research-touring-video-quality-ja.md puts the deadline at fifteen
seconds and the remedy in the vlogger's cold open -- the strongest moment
first, then back to the start. And a film that simply stops after its
last window has no ending; the well-regarded ones close on what the day
added up to and on one last picture.

So a judged film is framed here, after the chapters have been laid out.
The window the model ranked highest is lifted out of its chapter and
shown first, and the day's headline follows it: distance, time, climb --
what the track proves, and nothing it does not. At the end, a closing
card gives the same account and, when the last chapter has a window to
spare, one final picture follows it so the film ends on the road rather
than on text. A window is shown once; the plan already refuses to show
one twice, and this keeps to that.

Nothing here reads a place name or asks the rider anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.agents.story_planner import StoryOutputLanguage
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind

# Held long enough to read three numbers; the picture before it has
# already earned the viewer's attention.
HEADLINE_CARD_S = 6.0
CLOSING_CARD_S = 6.0
# The cold open: this many of the best windows, this long each.
HIGHLIGHT_COUNT = 4
HIGHLIGHT_S = 3.0


class StoryOpeningError(ValueError):
    """Raised when a film cannot be framed as asked."""


def frame_the_film(
    plan: JourneyStoryPlan,
    *,
    preference: Mapping[str, float],
    distance_m: float,
    duration_s: float,
    elevation_gain_m: float,
    elevation_loss_m: float,
    from_to: tuple[str | None, str | None] | None = None,
    route_chain: Sequence[str] = (),
    label: str | None = None,
    highlights: int = HIGHLIGHT_COUNT,
    highlight_s: float = HIGHLIGHT_S,
    highlight_ids: Sequence[str] | None = None,
) -> JourneyStoryPlan:
    """Open on a few highlights, run the chapters, and close on the day's account.

    The owner's day-1 notes (2026-09-07): the film opens on four short
    highlight clips, then the first chapter's full-screen card. There is
    no separate headline any more -- the first card says where the day
    begins, the closing card says where it went and what it added up to.
    `preference` orders the windows, lower first: the model's rank where
    one was bought, and otherwise something derived from its scores; a
    highlight is shown again in its own chapter, at full length. `label`
    ("Day 3") goes on every full-screen card. A plan with no footage is
    returned as it is.
    """
    if distance_m < 0 or duration_s <= 0 or elevation_gain_m < 0 or elevation_loss_m < 0:
        raise StoryOpeningError("a day's account needs a positive duration and no negative sum")
    if highlights < 0 or highlight_s <= 0:
        raise StoryOpeningError("the highlights must be a count and a positive length")
    footage = plan.footage_beats
    if not footage:
        return plan
    language = plan.output_language

    if highlight_ids:
        # The picker's choice (app.highlights), in ride order, where the
        # film shows those windows at all.
        wanted = [e for e in highlight_ids if any(b.event_id == e for b in footage)]
        chosen = sorted(
            (next(b for b in footage if b.event_id == e) for e in wanted[:highlights]),
            key=lambda beat: footage.index(beat),
        )
    else:
        best = sorted(footage, key=lambda beat: preference.get(beat.event_id or "", float("inf")))
        chosen = sorted(best[:highlights], key=lambda beat: footage.index(beat))
    opening = [
        StoryPlanBeat(
            kind=StoryBeatKind.FOOTAGE,
            screen_duration_s=min(highlight_s, beat.screen_duration_s),
            event_id=beat.event_id,
            source_offset_s=beat.source_offset_s,
            highlight=True,
        )
        for beat in chosen
    ]

    chain = _chain(route_chain)
    closing_body = _closing_body(distance_m, duration_s, language)
    account = _account(duration_s, elevation_gain_m, elevation_loss_m, language)
    closing_body = f"{chain}\n{closing_body}" if chain else f"{closing_body}\n{account}"
    closing = StoryPlanBeat(
        kind=StoryBeatKind.GAP_CARD,
        screen_duration_s=CLOSING_CARD_S,
        card=GapChapterCard(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            character=GapCharacter.CLOSE,
            title=_closing_title(language),
            body=closing_body,
            screen_duration_s=CLOSING_CARD_S,
            label=label,
        ),
    )

    body = [
        replace(beat, card=replace(beat.card, label=label))
        if beat.card is not None and label and beat.card.label is None
        else beat
        for beat in plan.beats
    ]
    # The arrival is the last picture; the closing card follows it and
    # nothing follows the card.
    beats = [*opening, *body, closing]
    footage_total = sum(b.screen_duration_s for b in beats if b.kind is StoryBeatKind.FOOTAGE)
    total = sum(b.screen_duration_s for b in beats)
    try:
        return replace(
            plan,
            beats=tuple(beats),
            footage_screen_duration_s=round(footage_total, 3),
            total_screen_duration_s=round(total, 3),
        )
    except ValueError as error:
        raise StoryOpeningError(str(error)) from error


def _account(duration_s: float, gain_m: float, loss_m: float, language: StoryOutputLanguage) -> str:
    hours, minutes = divmod(int(duration_s // 60), 60)
    if language is StoryOutputLanguage.JAPANESE:
        spent = f"{hours}時間{minutes:02d}分" if hours else f"{minutes}分"
        return f"{spent} · 登り{int(gain_m)}m / 下り{int(loss_m)}m"
    spent = f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
    return f"{spent} · +{int(gain_m)} m / -{int(loss_m)} m"


def _chain(places: Sequence[str]) -> str:
    """The places in order, each once where it repeats its neighbour."""
    chain: list[str] = []
    for place in places:
        if place and (not chain or chain[-1] != place):
            chain.append(place)
    return " → ".join(chain)


def _closing_title(language: StoryOutputLanguage) -> str:
    return "今日はここまで" if language is StoryOutputLanguage.JAPANESE else "That was the day"


def _closing_body(distance_m: float, duration_s: float, language: StoryOutputLanguage) -> str:
    hours, minutes = divmod(int(duration_s // 60), 60)
    kilometres = distance_m / 1000.0
    if language is StoryOutputLanguage.JAPANESE:
        spent = f"{hours}時間{minutes:02d}分" if hours else f"{minutes}分"
        return f"{kilometres:.1f}km · {spent}"
    spent = f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
    return f"{kilometres:.1f} km · {spent}"
