"""Put a chapter's title over its first window instead of on a card before it (E-4).

docs/research-touring-video-editing-ja.md §5.3 and §7: a full-screen card
between clips stops the ride for six seconds to say one line; a lower third
says it over the moving picture in five and hands the frame back. The
owner's own note kept the route figure and the short title, so both stay --
smaller, at the bottom of the frame, for the first seconds of the chapter's
first window.

The pass works on the plan, not on the film: a chapter card followed by a
window becomes that window carrying the card. The window keeps its length;
the card's screen time becomes how long the title stays up, capped so it
always leaves the window clean at the end. The headline and the close frame
the day and stay full-screen, and a chapter card with no window after it
(a chapter that happened but was never filmed) still says so on its own.
"""

from __future__ import annotations

from dataclasses import replace

from app.gap_chapters import GapCharacter
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind

# §5.2: a simple lower third stays three to five seconds, "long enough to
# read it all twice"; §7 E-4 names five.
LOWER_THIRD_S = 5.0
# The title leaves this much of the window untitled at the end, so a cut
# never lands with text still on screen.
CLEAR_TAIL_S = 1.0
# Below this the title could not be read twice; the card stays full-screen.
MIN_LOWER_THIRD_S = 3.0


def frames_the_day(character: GapCharacter) -> bool:
    """The cards whose picture is the whole day, kept full-screen."""
    return character in (GapCharacter.HEADLINE, GapCharacter.CLOSE)


def title_over_footage(plan: JourneyStoryPlan) -> JourneyStoryPlan:
    """Lay every chapter card onto the window that follows it, where one does."""
    beats = plan.beats
    laid: list[StoryPlanBeat] = []
    index = 0
    while index < len(beats):
        beat = beats[index]
        following = beats[index + 1] if index + 1 < len(beats) else None
        if _can_title(beat, following):
            assert beat.card is not None and following is not None
            stays_up = min(LOWER_THIRD_S, following.screen_duration_s - CLEAR_TAIL_S)
            laid.append(
                StoryPlanBeat(
                    kind=StoryBeatKind.FOOTAGE,
                    screen_duration_s=following.screen_duration_s,
                    event_id=following.event_id,
                    source_offset_s=following.source_offset_s,
                    card=replace(beat.card, screen_duration_s=round(stays_up, 3)),
                )
            )
            index += 2
            continue
        laid.append(beat)
        index += 1

    footage_total = sum(b.screen_duration_s for b in laid if b.kind is StoryBeatKind.FOOTAGE)
    total = sum(b.screen_duration_s for b in laid)
    return JourneyStoryPlan(
        beats=tuple(laid),
        output_language=plan.output_language,
        footage_screen_duration_s=round(footage_total, 3),
        total_screen_duration_s=round(total, 3),
    )


def _can_title(beat: StoryPlanBeat, following: StoryPlanBeat | None) -> bool:
    if beat.kind is not StoryBeatKind.GAP_CARD or beat.card is None:
        return False
    if frames_the_day(beat.card.character):
        return False
    if following is None or following.kind is not StoryBeatKind.FOOTAGE:
        return False
    if following.card is not None:
        return False
    return following.screen_duration_s - CLEAR_TAIL_S >= MIN_LOWER_THIRD_S
