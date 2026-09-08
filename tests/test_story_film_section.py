"""Synthetic-fixture tests for the section strip over a window (点 8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chapter_card import SECTION_HEIGHT_SHARE
from app.story_film import (
    SectionLayer,
    StoryFilmSegment,
    build_story_film_command,
    build_story_film_segments,
    write_section_strips,
)
from app.story_package import JourneyStoryPlan, SectionNote, StoryPlanBeat
from app.story_timeline import StoryBeatKind
from tests.test_story_film_lower_third import _sources
from tests.test_story_film_moving_route import _recording_runner


def _plan_with_section() -> JourneyStoryPlan:
    beats = (
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 10.0, event_id="w-open"),
        StoryPlanBeat(
            StoryBeatKind.FOOTAGE,
            8.0,
            event_id="w-1",
            section=SectionNote("town", "Ashfordを通る", 4.0),
        ),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2"),
    )
    return JourneyStoryPlan(
        beats=beats,
        output_language="ja",
        footage_screen_duration_s=24.0,
        total_screen_duration_s=24.0,
    )


def test_a_section_becomes_a_strip_page_and_a_layer_on_its_window(tmp_path: Path) -> None:
    plan = _plan_with_section()
    calls: list[list[str]] = []

    strips = write_section_strips(plan, tmp_path, runner=_recording_runner(calls))

    assert list(strips) == ["w-1"]
    assert (tmp_path / "story-cards" / "sec-001.html").is_file()
    assert "Ashfordを通る" in (tmp_path / "story-cards" / "sec-001.html").read_text(
        encoding="utf-8"
    )

    segments = build_story_film_segments(plan, [], _sources(tmp_path), section_strips=strips)
    with_strip = [s for s in segments if s.section is not None]
    assert [s.input_path.name for s in with_strip] == ["w-1.mp4"] or len(with_strip) == 1
    assert with_strip[0].section == SectionLayer(input_path=strips["w-1"], duration_s=4.0)


def test_the_command_adds_the_strip_as_an_input_and_keys_it_over_a_ninth_of_the_frame(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    strip = tmp_path / "sec-001.html.png"
    strip.write_bytes(b"x")
    segments = (
        StoryFilmSegment(
            kind=StoryBeatKind.FOOTAGE,
            input_path=clip,
            duration_s=8.0,
            source_start_s=0.0,
            section=SectionLayer(input_path=strip, duration_s=4.0),
        ),
    )

    command = build_story_film_command(
        segments, tmp_path / "out.mp4", width=1920, height=1080, fps=30
    )

    joined = " ".join(command)
    assert str(strip) in joined
    graph = command[command.index("-filter_complex") + 1]
    assert f"ih*{SECTION_HEIGHT_SHARE:.6f}" in graph
    assert "[x0]" in graph and "[x0]concat" in graph


def test_the_card_rasteriser_follows_the_machine_unless_it_is_told() -> None:
    """A package cut on someone else's machine should get the same cards without
    their having to know that macOS draws them one way and Linux another."""
    from app.story_film import HEADLESS_CHROMIUM, QUICK_LOOK, chosen_rasteriser

    assert chosen_rasteriser(platform="darwin", environ={}) is QUICK_LOOK
    assert chosen_rasteriser(platform="linux", environ={}) is HEADLESS_CHROMIUM
    assert chosen_rasteriser(platform="win32", environ={}) is HEADLESS_CHROMIUM
    told = {"RIDE_CARD_RASTERISER": "chromium"}
    assert chosen_rasteriser(platform="darwin", environ=told) is HEADLESS_CHROMIUM


def test_a_rasteriser_nobody_has_is_refused() -> None:
    from app.story_film import StoryFilmError, chosen_rasteriser

    with pytest.raises(StoryFilmError):
        chosen_rasteriser(environ={"RIDE_CARD_RASTERISER": "imagemagick"})
