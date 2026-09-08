"""Synthetic-fixture tests for the film's subtitle track."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.story_planner import StoryOutputLanguage
from app.journey_gaps import JourneyGapKind, JourneyGapPlan, JourneyGapSegment
from app.story_package import build_journey_story_plan
from app.story_subtitles import (
    StorySubtitleError,
    SubtitleCue,
    build_subtitle_cues,
    render_srt,
    render_webvtt,
)
from app.story_timeline import TimelineFootage, build_story_timeline

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _at(offset_s: float) -> datetime:
    return _START + timedelta(seconds=offset_s)


def _timeline():
    footage = tuple(
        TimelineFootage(
            event_id=f"evt_{index}",
            start_time=_at(3600.0 * (index + 1)),
            end_time=_at(3600.0 * (index + 1) + 30.0),
        )
        for index in range(2)
    )
    gaps = (
        JourneyGapSegment(
            kind=JourneyGapKind.BEFORE_FIRST_CLIP,
            start_time=_at(0.0),
            end_time=_at(3600.0),
            distance_m=42_000.0,
            elevation_gain_m=300.0,
            elevation_loss_m=120.0,
        ),
        JourneyGapSegment(
            kind=JourneyGapKind.AFTER_LAST_CLIP,
            start_time=_at(7230.0),
            end_time=_at(9000.0),
            distance_m=12_000.0,
            elevation_gain_m=20.0,
            elevation_loss_m=180.0,
        ),
    )
    return build_story_timeline(footage, JourneyGapPlan(gaps))


def _plan(language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE):
    return build_journey_story_plan(_timeline(), output_language=language)


def test_a_cue_is_written_for_every_card_and_no_footage() -> None:
    """Nothing is said over the footage, so nothing is captioned there."""
    plan = _plan()

    cues = build_subtitle_cues(plan)

    assert len(cues) == len(plan.card_beats)


def test_cues_are_timed_by_everything_before_them() -> None:
    plan = _plan()

    cues = build_subtitle_cues(plan)

    assert cues[0].start_s == pytest.approx(0.0)
    assert cues[0].end_s == pytest.approx(plan.beats[0].screen_duration_s)
    # The second card follows a card, two clips, and nothing else.
    before_second_card = sum(beat.screen_duration_s for beat in plan.beats[:-1])
    assert cues[1].start_s == pytest.approx(before_second_card)


def test_cues_never_overlap_and_stay_inside_the_film() -> None:
    plan = _plan()

    cues = build_subtitle_cues(plan)

    for earlier, later in zip(cues, cues[1:], strict=False):
        assert earlier.end_s <= later.start_s
    assert cues[-1].end_s <= plan.total_screen_duration_s + 1e-6


def test_a_cue_says_what_the_card_says() -> None:
    plan = _plan()

    cue = build_subtitle_cues(plan)[0]

    assert plan.card_beats[0].card.title in cue.text
    assert plan.card_beats[0].card.body in cue.text


def test_subtitles_follow_the_film_language() -> None:
    """The words on screen and the words in the track must not disagree."""
    japanese = build_subtitle_cues(_plan(StoryOutputLanguage.JAPANESE))
    english = build_subtitle_cues(_plan(StoryOutputLanguage.ENGLISH))

    assert "旅の始まり" in japanese[0].text
    assert "The ride begins" in english[0].text
    # Timing is a property of the plan, not the language.
    assert [cue.start_s for cue in japanese] == pytest.approx([cue.start_s for cue in english])
    assert [cue.end_s for cue in japanese] == pytest.approx([cue.end_s for cue in english])


def test_cues_hold_no_private_identifier() -> None:
    plan = _plan()

    joined = render_srt(build_subtitle_cues(plan))

    for forbidden in ("evt_", "2026-05-01", "latitude", "longitude", ".mp4"):
        assert forbidden not in joined


def test_srt_is_numbered_from_one_with_comma_milliseconds() -> None:
    srt = render_srt(build_subtitle_cues(_plan()))

    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "\n2\n" in srt


def test_webvtt_starts_with_its_header_and_uses_dot_milliseconds() -> None:
    vtt = render_webvtt(build_subtitle_cues(_plan()))

    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> " in vtt
    assert "," not in vtt.split("-->")[0]


def test_timestamps_carry_hours_minutes_seconds_and_milliseconds() -> None:
    cues = (SubtitleCue(index=1, start_s=3_725.5, end_s=3_730.25, text="x"),)

    srt = render_srt(cues)

    assert "01:02:05,500 --> 01:02:10,250" in srt


def test_an_empty_track_is_refused() -> None:
    with pytest.raises(StorySubtitleError, match="at least one cue"):
        render_srt(())
    with pytest.raises(StorySubtitleError, match="at least one cue"):
        render_webvtt(())


def test_a_cue_too_brief_to_read_is_refused() -> None:
    with pytest.raises(ValueError, match="long enough to read"):
        SubtitleCue(index=1, start_s=0.0, end_s=0.4, text="x")


def test_a_cue_without_text_or_a_valid_number_is_refused() -> None:
    with pytest.raises(ValueError, match="needs text"):
        SubtitleCue(index=1, start_s=0.0, end_s=5.0, text="   ")
    with pytest.raises(ValueError, match="numbered from one"):
        SubtitleCue(index=0, start_s=0.0, end_s=5.0, text="x")
    with pytest.raises(ValueError, match="before the film"):
        SubtitleCue(index=1, start_s=-1.0, end_s=5.0, text="x")
