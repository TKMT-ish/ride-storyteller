"""Write the film's subtitles from the same plan the film was cut from.

Gate 3 of docs/completion-roadmap-ja.md. The film has no narration, so a
subtitle here is not a transcript of speech; it is the on-screen chapter text
made available as a track, timed to the beat it belongs to. That is what lets
the words be read by someone using a player's caption track, and what gives
the submission its subtitle file without re-cutting the picture.

Footage beats carry no cue. Nothing is said over them, and the film makes no
claim about what they show beyond the fact that they were filmed there. A cue
invented to fill the silence would be exactly the kind of claim the rest of
this project refuses to make.

Subtitles are written in the plan's own language: a Japanese film gets
Japanese cards and Japanese cues, an English film gets both in English, so
the words on screen and the words in the track never disagree. Burning them
into the picture is deliberately not done — one language per render would
then mean re-encoding the whole film to change language, and the timing
here is identical across languages by construction.

A cue holds only the card's own text, which is drawn from GPS aggregates:
no coordinate, capture time, event ID, asset ID, path, or file name.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.story_package import JourneyStoryPlan
from app.story_timeline import StoryBeatKind

SUBTITLE_SCHEMA_VERSION = "story-subtitles-v1"

# A cue shorter than this flashes past unread; the plan's floor for a card is
# above it, so this only guards against a hand-built plan.
_MINIMUM_CUE_S = 1.0


class StorySubtitleError(ValueError):
    """Raised when subtitles cannot be written for a plan."""


@dataclass(frozen=True)
class SubtitleCue:
    """One line of text, held over one stretch of the film."""

    index: int
    start_s: float
    end_s: float
    text: str

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError("subtitle cues are numbered from one")
        if self.start_s < 0:
            raise ValueError("a subtitle cue cannot start before the film")
        if self.end_s - self.start_s < _MINIMUM_CUE_S:
            raise ValueError("a subtitle cue must be held long enough to read")
        if not self.text.strip():
            raise ValueError("a subtitle cue needs text")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def build_subtitle_cues(plan: JourneyStoryPlan) -> tuple[SubtitleCue, ...]:
    """Time every chapter card against the film the plan describes.

    Beats are laid end to end in plan order, so a cue's position is the sum
    of everything before it. Footage beats advance the clock and produce no
    cue of their own.
    """
    cues: list[SubtitleCue] = []
    elapsed = 0.0
    for beat in plan.beats:
        if beat.kind is StoryBeatKind.GAP_CARD:
            assert beat.card is not None
            try:
                cues.append(
                    SubtitleCue(
                        index=len(cues) + 1,
                        start_s=elapsed,
                        end_s=elapsed + beat.screen_duration_s,
                        text=f"{beat.card.title}\n{beat.card.body}",
                    )
                )
            except ValueError as error:
                raise StorySubtitleError(str(error)) from error
        elapsed += beat.screen_duration_s
    return tuple(cues)


def render_srt(cues: tuple[SubtitleCue, ...]) -> str:
    """Render cues as SubRip, the format players and Devpost both accept."""
    if not cues:
        raise StorySubtitleError("a subtitle track needs at least one cue")
    blocks = [
        f"{cue.index}\n{_timestamp(cue.start_s)} --> {_timestamp(cue.end_s)}\n{cue.text}\n"
        for cue in cues
    ]
    return "\n".join(blocks)


def render_webvtt(cues: tuple[SubtitleCue, ...]) -> str:
    """Render the same cues as WebVTT, for playing the film in a browser."""
    if not cues:
        raise StorySubtitleError("a subtitle track needs at least one cue")
    blocks = [
        f"{_timestamp(cue.start_s, separator='.')} --> "
        f"{_timestamp(cue.end_s, separator='.')}\n{cue.text}\n"
        for cue in cues
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)


def _timestamp(seconds: float, *, separator: str = ",") -> str:
    if seconds < 0:
        raise StorySubtitleError("a subtitle timestamp cannot be negative")
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
