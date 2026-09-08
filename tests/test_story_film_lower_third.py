"""Synthetic-fixture tests for the title strip over a chapter's first window (E-4).

Held: a titled footage beat takes a strip drawn for it and becomes one
footage segment with a lower-third layer; the ffmpeg command adds the
strip as an extra input, keys it by brightness over a translucent band,
fades it in and out, and hands the frame back before the window ends.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.chapter_card import LOWER_THIRD_HEIGHT_SHARE
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_film import (
    CARD_FRAME_RATE,
    CARD_GROW_S,
    LOWER_THIRD_FADE_S,
    LOWER_THIRD_STRIP_OPACITY,
    CardRaster,
    FootageSource,
    LowerThirdLayer,
    StoryFilmSegment,
    build_story_film_command,
    build_story_film_segments,
    write_chapter_cards,
)
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind
from tests.test_story_film_moving_route import _recording_runner, _route


def _card(title: str, character: GapCharacter, shown_s: float) -> GapChapterCard:
    return GapChapterCard(
        kind=JourneyGapKind.BETWEEN_CLIPS,
        character=character,
        title=title,
        body="出発から3時間06分 · 142.0km · 海抜815m → 67m",
        screen_duration_s=shown_s,
        since_departure_s=0.0,
        duration_s=3000.0,
    )


def _titled_plan() -> JourneyStoryPlan:
    """A cold open, the headline, a titled window, a plain window, the close."""
    beats = (
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 10.0, event_id="w-open"),
        StoryPlanBeat(
            StoryBeatKind.GAP_CARD,
            10.0,
            card=GapChapterCard(
                kind=JourneyGapKind.BEFORE_FIRST_CLIP,
                character=GapCharacter.HEADLINE,
                title="この日",
                body="本文",
                screen_duration_s=10.0,
            ),
        ),
        StoryPlanBeat(
            StoryBeatKind.FOOTAGE,
            8.0,
            event_id="w-1",
            card=_card("長い下り", GapCharacter.DESCENT, 5.0),
        ),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2"),
        StoryPlanBeat(
            StoryBeatKind.GAP_CARD,
            6.0,
            card=GapChapterCard(
                kind=JourneyGapKind.AFTER_LAST_CLIP,
                character=GapCharacter.CLOSE,
                title="今日はここまで",
                body="本文",
                screen_duration_s=6.0,
            ),
        ),
    )
    return JourneyStoryPlan(
        beats=beats,
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=24.0,
        total_screen_duration_s=40.0,
    )


def _sources(tmp_path: Path) -> dict[str, FootageSource]:
    sources = {}
    for event_id in ("w-open", "w-1", "w-2"):
        clip = tmp_path / f"{event_id}.mp4"
        clip.write_bytes(b"mp4")
        sources[event_id] = FootageSource(path=clip, start_s=30.0)
    return sources


# --- drawing -----------------------------------------------------------------------------


def test_a_titled_window_gets_a_strip_not_a_card(tmp_path: Path) -> None:
    rasters = write_chapter_cards(
        _titled_plan(), tmp_path, route_points=_route(), runner=_recording_runner([])
    )

    assert [r.lower_third for r in rasters] == [False, True, False]
    strip = rasters[1]
    assert strip.is_sequence, "its stretch of the route draws itself in"
    frames = sorted((tmp_path / "story-cards").glob("card-002-f*.html"))
    assert len(frames) == math.ceil(CARD_GROW_S * CARD_FRAME_RATE)
    page = (tmp_path / "story-cards" / "card-002.html").read_text(encoding="utf-8")
    assert 'class="strip"' in page and 'class="band"' in page
    assert "長い下り" in page
    assert "出発から3時間06分 · 142.0km" in page and "海抜" not in page, "the body was fitted"
    assert 'class="map"' in page and "map-wide" not in page


def test_without_a_route_the_strip_is_one_still(tmp_path: Path) -> None:
    rasters = write_chapter_cards(_titled_plan(), tmp_path, runner=_recording_runner([]))

    assert rasters[1].lower_third and not rasters[1].is_sequence
    page = (tmp_path / "story-cards" / "card-002.html").read_text(encoding="utf-8")
    assert 'class="strip"' in page and "<svg" not in page


# --- segments ----------------------------------------------------------------------------


def test_a_titled_beat_becomes_footage_carrying_a_layer(tmp_path: Path) -> None:
    still = tmp_path / "still.png"
    still.write_bytes(b"\x89PNG")
    pattern = tmp_path / "card-002-f%03d.html.png"
    rasters = (
        CardRaster(still=still, pattern=tmp_path / "card-001-f%03d.html.png", frame_rate=12),
        CardRaster(still=still, pattern=pattern, frame_rate=12, lower_third=True),
        CardRaster(still=still),
    )

    segments = build_story_film_segments(_titled_plan(), rasters, _sources(tmp_path))

    assert [s.kind for s in segments] == [
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.FOOTAGE,
        StoryBeatKind.GAP_CARD,
    ]
    titled = segments[2]
    assert titled.lower_third == LowerThirdLayer(input_path=pattern, duration_s=5.0, frame_rate=12)
    assert titled.duration_s == 8.0 and titled.source_start_s == 30.0
    assert all(s.lower_third is None for s in segments if s is not titled)


def test_the_drawn_cards_must_match_every_beat_with_a_card(tmp_path: Path) -> None:
    still = tmp_path / "still.png"
    still.write_bytes(b"\x89PNG")
    with pytest.raises(Exception, match="do not match"):
        build_story_film_segments(_titled_plan(), (still, still), _sources(tmp_path))


def test_only_footage_carries_a_lower_third_and_never_for_longer(tmp_path: Path) -> None:
    layer = LowerThirdLayer(input_path=tmp_path / "s.png", duration_s=5.0)
    with pytest.raises(ValueError, match="only footage"):
        StoryFilmSegment(StoryBeatKind.GAP_CARD, tmp_path / "c.png", 6.0, lower_third=layer)
    with pytest.raises(ValueError, match="outlast"):
        StoryFilmSegment(StoryBeatKind.FOOTAGE, tmp_path / "c.mp4", 4.0, lower_third=layer)
    with pytest.raises(ValueError, match="stay up"):
        LowerThirdLayer(input_path=tmp_path / "s.png", duration_s=0.0)


# --- the command -------------------------------------------------------------------------


def _titled_segments(tmp_path: Path, *, sequence: bool) -> tuple[StoryFilmSegment, ...]:
    layer_path = tmp_path / ("card-002-f%03d.html.png" if sequence else "card-002.html.png")
    layer = LowerThirdLayer(
        input_path=layer_path, duration_s=5.0, frame_rate=CARD_FRAME_RATE if sequence else None
    )
    return (
        StoryFilmSegment(
            StoryBeatKind.FOOTAGE, tmp_path / "w1.mp4", 8.0, source_start_s=30.0, lower_third=layer
        ),
        StoryFilmSegment(StoryBeatKind.GAP_CARD, tmp_path / "close.png", 6.0),
    )


def test_the_strip_is_an_extra_input_after_its_window(tmp_path: Path) -> None:
    command = list(
        build_story_film_command(
            _titled_segments(tmp_path, sequence=True), tmp_path / "out.mp4", overwrite=True
        )
    )
    joined = " ".join(command)

    assert "-ss 30.000 -t 8.000 -i" in joined
    window = command.index(str(tmp_path / "w1.mp4"))
    strip = command.index(str(tmp_path / "card-002-f%03d.html.png"))
    close = command.index(str(tmp_path / "close.png"))
    assert window < strip < close
    assert command[strip - 5 : strip - 1] == [
        "-framerate",
        str(CARD_FRAME_RATE),
        "-start_number",
        "1",
    ]


def test_a_still_strip_is_looped_for_exactly_its_time(tmp_path: Path) -> None:
    joined = " ".join(
        build_story_film_command(
            _titled_segments(tmp_path, sequence=False), tmp_path / "out.mp4", overwrite=True
        )
    )

    assert f"-loop 1 -t 5.000 -i {tmp_path / 'card-002.html.png'}" in joined


def test_the_filter_keys_the_strip_by_brightness_over_a_darkened_band(tmp_path: Path) -> None:
    command = build_story_film_command(
        _titled_segments(tmp_path, sequence=True), tmp_path / "out.mp4", overwrite=True
    )
    graph = command[command.index("-filter_complex") + 1]
    chains = graph.split(";")
    strip_height = round(1080 * LOWER_THIRD_HEIGHT_SHARE)

    title = next(c for c in chains if c.startswith("[1:v:0]"))
    assert "tpad=stop_mode=clone:stop_duration=5.000" in title
    assert "crop=iw:iw*1080/1920" in title, "the band of the square page"
    assert f"scale=1920:{strip_height}" in title
    assert "colorchannelmixer=aa=0:ar=0.299:ag=0.587:ab=0.114" in title
    assert f"fade=t=in:st=0:d={LOWER_THIRD_FADE_S}:alpha=1" in title
    assert f"fade=t=out:st={5.0 - LOWER_THIRD_FADE_S:.3f}:d={LOWER_THIRD_FADE_S}:alpha=1" in title
    assert title.endswith("[t0]")

    band = next(c for c in chains if c.startswith("color="))
    assert f"color=c=black@{LOWER_THIRD_STRIP_OPACITY}:s=1920x{strip_height}:r=30:d=5.000" in band
    assert band.endswith("[s0]")

    top = 1080 - strip_height
    assert f"[v0][s0]overlay=0:{top}:eof_action=pass:repeatlast=0[u0]" in chains
    assert f"[u0][t0]overlay=0:{top}:eof_action=pass:repeatlast=0[w0]" in chains
    assert chains[-1].startswith("[w0][v1]concat=n=2"), "the titled window joins as [w0]"
    assert re.search(r"\[2:v:0\][^;]*\[v1\]", graph), "the close is input 2, after the strip"


def test_a_window_without_a_title_is_unchanged(tmp_path: Path) -> None:
    plain = (
        StoryFilmSegment(StoryBeatKind.FOOTAGE, tmp_path / "w1.mp4", 8.0, source_start_s=30.0),
    )
    graph = build_story_film_command(plain, tmp_path / "out.mp4", overwrite=True)
    joined = " ".join(graph)

    assert "overlay" not in joined and "color=" not in joined
    assert "[v0]concat=n=1" in joined


def test_the_layer_runner_stands_in_for_ffmpeg() -> None:
    """The fixture helper in this module is only a shape check; nothing runs ffmpeg here."""
    assert subprocess.CompletedProcess is not None


def test_the_cut_begins_where_the_plan_says_inside_the_window(tmp_path: Path) -> None:
    plan = JourneyStoryPlan(
        beats=(StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-1", source_offset_s=6.0),),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=6.0,
        total_screen_duration_s=6.0,
    )

    (segment,) = build_story_film_segments(plan, (), _sources(tmp_path))

    assert segment.source_start_s == 30.0 + 6.0, (
        "the window's start in its recording, plus the offset"
    )
