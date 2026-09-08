"""The film and its subtitles must be cut from the same clock.

Both are derived from one journey story plan, but by separate code paths:
`app.story_film` lays beats end to end as FFmpeg inputs, and
`app.story_subtitles` lays the same beats end to end as cue times. Nothing
forces those two walks to agree. If one changed how a beat's duration is
taken and the other did not, the captions would drift away from the cards
they describe — silently, and only visible by watching the finished film.

That was checked by hand once, on real material, by extracting a frame at
every cue and confirming the right card was on screen. These tests hold the
property so it does not have to be checked by hand again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_film import FootageSource, build_story_film_segments
from app.story_package import build_journey_story_plan
from app.story_subtitles import build_subtitle_cues
from app.story_timeline import StoryBeatKind, TimelineFootage, build_story_timeline

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _plan(
    *,
    footage_count: int = 3,
    language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
):
    """A ride that opens and closes unfilmed, with footage in between."""
    footage = tuple(
        TimelineFootage(
            event_id=f"evt_{index}",
            start_time=_at(3600.0 * (index + 1)),
            end_time=_at(3600.0 * (index + 1) + 30.0),
        )
        for index in range(footage_count)
    )
    gaps = [
        JourneyGapSegment(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            start_time=_at(0.0),
            end_time=_at(3600.0),
            distance_m=42_000.0,
            elevation_gain_m=300.0,
            elevation_loss_m=120.0,
        )
    ]
    for index in range(footage_count - 1):
        gaps.append(
            JourneyGapSegment(
                kind=JourneyGapKind.BETWEEN_CLIPS,
                start_time=_at(3600.0 * (index + 1) + 30.0),
                end_time=_at(3600.0 * (index + 2)),
                distance_m=18_000.0 * (index + 1),
                elevation_gain_m=90.0,
                elevation_loss_m=310.0,
            )
        )
    gaps.append(
        JourneyGapSegment(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            start_time=_at(3600.0 * footage_count + 30.0),
            end_time=_at(3600.0 * (footage_count + 1)),
            distance_m=12_000.0,
            elevation_gain_m=20.0,
            elevation_loss_m=280.0,
        )
    )
    return build_journey_story_plan(
        build_story_timeline(footage, JourneyGapPlan(tuple(gaps))),
        output_language=language,
    )


def _segments(plan, tmp_path: Path):
    cards = []
    for index in range(len(plan.card_beats)):
        card = tmp_path / f"card-{index}.png"
        card.write_bytes(b"\x89PNG")
        cards.append(card)
    sources = {}
    for beat in plan.footage_beats:
        recording = tmp_path / f"{beat.event_id}.mp4"
        recording.write_bytes(b"clip")
        sources[beat.event_id] = FootageSource(path=recording, start_s=0.0)
    return build_story_film_segments(plan, tuple(cards), sources)


def _cue_windows_from_segments(plan, segments) -> list[tuple[float, float]]:
    """Where each card sits in the cut, walked through the film's own segments."""
    windows: list[tuple[float, float]] = []
    elapsed = 0.0
    for beat, segment in zip(plan.beats, segments, strict=True):
        if beat.kind is StoryBeatKind.GAP_CARD:
            windows.append((elapsed, elapsed + segment.duration_s))
        elapsed += segment.duration_s
    return windows


@pytest.mark.parametrize("footage_count", [1, 3, 6])
def test_every_cue_covers_the_card_the_film_shows(footage_count: int, tmp_path: Path) -> None:
    plan = _plan(footage_count=footage_count)
    segments = _segments(plan, tmp_path)

    cues = build_subtitle_cues(plan)
    windows = _cue_windows_from_segments(plan, segments)

    assert len(cues) == len(windows)
    for cue, (start, end) in zip(cues, windows, strict=True):
        assert cue.start_s == pytest.approx(start)
        assert cue.end_s == pytest.approx(end)


def test_a_cue_says_what_its_card_says(tmp_path: Path) -> None:
    plan = _plan()

    cues = build_subtitle_cues(plan)

    for cue, beat in zip(cues, plan.card_beats, strict=True):
        assert beat.card is not None
        assert beat.card.title in cue.text
        assert beat.card.body in cue.text


def test_the_film_and_the_captions_end_together(tmp_path: Path) -> None:
    """This ride closes on a card, so the last cue must reach the last frame."""
    plan = _plan()
    segments = _segments(plan, tmp_path)

    cues = build_subtitle_cues(plan)

    assert plan.beats[-1].kind is StoryBeatKind.GAP_CARD
    assert sum(segment.duration_s for segment in segments) == pytest.approx(
        plan.total_screen_duration_s
    )
    assert cues[-1].end_s == pytest.approx(plan.total_screen_duration_s)


def test_captions_never_run_over_footage(tmp_path: Path) -> None:
    """Nothing is said over the footage, so no cue may extend into it."""
    plan = _plan()
    segments = _segments(plan, tmp_path)

    cues = build_subtitle_cues(plan)
    footage_windows = []
    elapsed = 0.0
    for beat, segment in zip(plan.beats, segments, strict=True):
        if beat.kind is StoryBeatKind.FOOTAGE:
            footage_windows.append((elapsed, elapsed + segment.duration_s))
        elapsed += segment.duration_s

    for cue in cues:
        for start, end in footage_windows:
            assert cue.end_s <= start or cue.start_s >= end


def test_language_does_not_move_a_single_cue() -> None:
    """A different language must not require re-cutting the picture."""
    japanese = build_subtitle_cues(_plan(language=StoryOutputLanguage.JAPANESE))
    english = build_subtitle_cues(_plan(language=StoryOutputLanguage.ENGLISH))

    assert [cue.start_s for cue in japanese] == pytest.approx([cue.start_s for cue in english])
    assert [cue.end_s for cue in japanese] == pytest.approx([cue.end_s for cue in english])
    # Same clock, different words.
    assert [cue.text for cue in japanese] != [cue.text for cue in english]
