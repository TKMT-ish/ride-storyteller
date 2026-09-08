"""Synthetic-fixture tests for the route that draws itself on a chapter card (E-3).

A card with the ride's track is no longer one still: its stretch of the
route grows in over the first seconds and then holds, the headline card
draws the whole day, and the close shows it drawn. The frames are pages
like any card, drawn together in one call, and the film takes them as a
numbered sequence that holds its last frame for the rest of the beat.
"""

from __future__ import annotations

import math
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agents import StoryOutputLanguage
from app.contracts import RoutePoint
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind
from app.story_film import (
    CARD_FRAME_RATE,
    CARD_GROW_S,
    HEADLESS_CHROMIUM,
    HEADLINE_GROW_S,
    CardRaster,
    StoryFilmError,
    StoryFilmSegment,
    build_story_film_command,
    build_story_film_segments,
    write_chapter_cards,
)
from app.story_package import JourneyStoryPlan, StoryPlanBeat
from app.story_timeline import StoryBeatKind

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _route(count: int = 200) -> tuple[RoutePoint, ...]:
    return tuple(
        RoutePoint(
            latitude=35.0 + 0.001 * i,
            longitude=139.0 + 0.0007 * i,
            elevation_m=100.0 + i,
            timestamp=_T0 + timedelta(seconds=60 * i),
            distance_from_start_m=120.0 * i,
            speed_mps=8.0,
        )
        for i in range(count)
    )


def _card(
    title: str,
    character: GapCharacter,
    kind: JourneyGapKind,
    hold_s: float,
    *,
    since_s: float | None = None,
    for_s: float | None = None,
) -> StoryPlanBeat:
    return StoryPlanBeat(
        StoryBeatKind.GAP_CARD,
        hold_s,
        card=GapChapterCard(
            kind=kind,
            character=character,
            title=title,
            body="本文",
            screen_duration_s=hold_s,
            since_departure_s=since_s,
            duration_s=for_s,
        ),
    )


def _plan() -> JourneyStoryPlan:
    """Cold open, headline, two chapters with a window each, and a close."""
    beats = (
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 10.0, event_id="w-open"),
        _card("この日", GapCharacter.HEADLINE, JourneyGapKind.BEFORE_FIRST_CLIP, 10.0),
        _card("出発", GapCharacter.DEPARTURE, JourneyGapKind.BETWEEN_CLIPS, 6.0),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1"),
        _card("登りが続く", GapCharacter.CLIMB, JourneyGapKind.BETWEEN_CLIPS, 6.0),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2"),
        _card("今日はここまで", GapCharacter.CLOSE, JourneyGapKind.AFTER_LAST_CLIP, 6.0),
    )
    return JourneyStoryPlan(
        beats=beats,
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=24.0,
        total_screen_duration_s=52.0,
    )


def _recording_runner(calls: list[list[str]]):
    """Stand in for Quick Look: one PNG per page named in the command."""

    def run(command, check=False, capture_output=True, text=True, timeout=60):
        calls.append(list(command))
        out_dir = Path(command[command.index("-o") + 1])
        for argument in command:
            if str(argument).endswith(".html"):
                (out_dir / f"{Path(argument).name}.png").write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    return run


def _highlight_length(html_path: Path) -> int:
    """How many points the picked-out stretch has in this page's map."""
    html = html_path.read_text(encoding="utf-8")
    here = re.search(r'class="here" points="([^"]*)"', html)
    return len(here.group(1).split()) if here else 0


# --- what is drawn ----------------------------------------------------------------


def test_a_chapter_card_becomes_a_run_of_frames_that_hold_at_the_end(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    rasters = write_chapter_cards(
        _plan(), tmp_path, route_points=_route(), runner=_recording_runner(calls)
    )

    departure = rasters[1]
    assert departure.is_sequence
    assert departure.frame_rate == CARD_FRAME_RATE
    frames = sorted((tmp_path / "story-cards").glob("card-002-f*.html"))
    assert len(frames) == math.ceil(CARD_GROW_S * CARD_FRAME_RATE)
    lengths = [_highlight_length(f) for f in frames]
    assert lengths == sorted(lengths), "the stretch must only grow"
    assert lengths[0] < lengths[-1]
    assert departure.pattern is not None and "%03d" in departure.pattern.name
    assert departure.still.is_file(), "the finished drawing is kept as the still"


def test_the_headline_draws_the_whole_day_and_the_close_shows_it_drawn(tmp_path: Path) -> None:
    route = _route()
    rasters = write_chapter_cards(
        _plan(), tmp_path, route_points=route, runner=_recording_runner([])
    )

    headline = rasters[0]
    assert headline.is_sequence
    headline_frames = sorted((tmp_path / "story-cards").glob("card-001-f*.html"))
    assert len(headline_frames) == math.ceil(HEADLINE_GROW_S * CARD_FRAME_RATE)
    whole = _highlight_length(tmp_path / "story-cards" / "card-001.html")
    assert _highlight_length(headline_frames[-1]) == whole
    assert _highlight_length(headline_frames[0]) < whole / 4

    close = rasters[-1]
    assert not close.is_sequence, "the close is one still of the route drawn"
    assert _highlight_length(tmp_path / "story-cards" / "card-004.html") == whole


def test_chapters_share_the_route_between_themselves_not_with_the_headline(tmp_path: Path) -> None:
    """A headline or a close must not push the first chapter off the ride's start."""
    write_chapter_cards(_plan(), tmp_path, route_points=_route(), runner=_recording_runner([]))

    first_chapter = (tmp_path / "story-cards" / "card-002.html").read_text(encoding="utf-8")
    second_chapter = (tmp_path / "story-cards" / "card-003.html").read_text(encoding="utf-8")
    whole = re.search(r'class="route" points="([^"]*)"', first_chapter).group(1).split()
    first_here = re.search(r'class="here" points="([^"]*)"', first_chapter).group(1).split()
    second_here = re.search(r'class="here" points="([^"]*)"', second_chapter).group(1).split()
    assert first_here[0] == whole[0], "the first chapter starts where the ride starts"
    assert second_here[-1] == whole[-1], "the last chapter ends where the ride ends"


def test_every_frame_of_every_card_is_drawn_in_one_call(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    write_chapter_cards(_plan(), tmp_path, route_points=_route(), runner=_recording_runner(calls))

    assert len(calls) == 1, "Quick Look takes every page at once; starting it is the cost"
    pages = [a for a in calls[0] if str(a).endswith(".html")]
    assert len(pages) == len(list((tmp_path / "story-cards").glob("*.html")))


def test_a_rasteriser_that_cannot_batch_is_called_once_per_page(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, check=False, capture_output=True, text=True, timeout=60):
        calls.append(list(command))
        for argument in command:
            if str(argument).startswith("--screenshot="):
                Path(str(argument).split("=", 1)[1]).write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    write_chapter_cards(
        _plan(), tmp_path, route_points=_route(), rasteriser=HEADLESS_CHROMIUM, runner=runner
    )

    assert len(calls) == len(list((tmp_path / "story-cards").glob("*.html")))


def test_without_animation_or_a_route_every_card_is_one_still(tmp_path: Path) -> None:
    quiet = write_chapter_cards(
        _plan(), tmp_path / "a", route_points=_route(), animate=False, runner=_recording_runner([])
    )
    no_route = write_chapter_cards(_plan(), tmp_path / "b", runner=_recording_runner([]))

    assert all(not r.is_sequence for r in quiet)
    assert all(not r.is_sequence for r in no_route)
    assert not list((tmp_path / "a" / "story-cards").glob("*-f*.html"))


def test_a_frame_rate_that_is_not_positive_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryFilmError, match="frame rate"):
        write_chapter_cards(_plan(), tmp_path, route_points=_route(), frame_rate=0)


# --- how the film takes it -----------------------------------------------------------


def test_a_sequence_segment_holds_its_last_frame_for_the_rest_of_the_beat(tmp_path: Path) -> None:
    pattern = tmp_path / "card-002-f%03d.html.png"
    segment = StoryFilmSegment(
        StoryBeatKind.GAP_CARD, pattern, duration_s=6.0, frame_rate=CARD_FRAME_RATE
    )

    command = " ".join(build_story_film_command((segment,), tmp_path / "out.mp4", overwrite=True))

    assert f"-framerate {CARD_FRAME_RATE} -start_number 1 -i {pattern}" in command
    assert "-loop 1" not in command
    assert "tpad=stop_mode=clone:stop_duration=6.000" in command
    assert "trim=duration=6.000" in command
    assert "setpts=PTS-STARTPTS" in command
    assert "crop=iw:iw*1080/1920" in command, "a card is still cropped to the film's band"


def test_segments_take_the_frames_when_a_card_moves_and_the_still_when_it_does_not(
    tmp_path: Path,
) -> None:
    plan = _plan()
    sources = {}
    for event_id in ("w-open", "w-1", "w-2"):
        clip = tmp_path / f"{event_id}.mp4"
        clip.write_bytes(b"mp4")
        from app.story_film import FootageSource

        sources[event_id] = FootageSource(path=clip, start_s=0.0)
    still = tmp_path / "still.png"
    still.write_bytes(b"\x89PNG")
    pattern = tmp_path / "card-%03d.png"
    drawn = (
        CardRaster(still=still, pattern=pattern, frame_rate=12),
        CardRaster(still=still),
        still,  # a bare path is still accepted
        CardRaster(still=still),
    )

    segments = build_story_film_segments(plan, drawn, sources)

    cards = [s for s in segments if s.kind is StoryBeatKind.GAP_CARD]
    assert cards[0].is_sequence and cards[0].input_path == pattern and cards[0].frame_rate == 12
    assert all(not c.is_sequence and c.input_path == still for c in cards[1:])


def test_only_a_card_may_be_a_frame_sequence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only a card"):
        StoryFilmSegment(StoryBeatKind.FOOTAGE, tmp_path / "x.mp4", 5.0, frame_rate=12)
    with pytest.raises(ValueError, match="positive rate"):
        StoryFilmSegment(StoryBeatKind.GAP_CARD, tmp_path / "x.png", 5.0, frame_rate=0)


# --- where the stretch is cut ----------------------------------------------------------


def _clock_plan() -> JourneyStoryPlan:
    """Headline, a chapter, a halt, a chapter, a close -- every chapter on the clock.

    The route has a point a minute; the first chapter runs 0-50 min, the halt
    50-70 min, the last chapter 70 min to the end.
    """
    beats = (
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 10.0, event_id="w-open"),
        _card("この日", GapCharacter.HEADLINE, JourneyGapKind.BEFORE_FIRST_CLIP, 10.0),
        _card(
            "出発",
            GapCharacter.DEPARTURE,
            JourneyGapKind.BETWEEN_CLIPS,
            6.0,
            since_s=0.0,
            for_s=3000.0,
        ),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 8.0, event_id="w-1"),
        _card(
            "ここで休む",
            GapCharacter.HALT,
            JourneyGapKind.BETWEEN_CLIPS,
            6.0,
            since_s=3000.0,
            for_s=1200.0,
        ),
        _card(
            "海沿い",
            GapCharacter.COAST,
            JourneyGapKind.BETWEEN_CLIPS,
            6.0,
            since_s=4200.0,
            for_s=7740.0,
        ),
        StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-2"),
        _card("今日はここまで", GapCharacter.CLOSE, JourneyGapKind.AFTER_LAST_CLIP, 6.0),
    )
    return JourneyStoryPlan(
        beats=beats,
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=24.0,
        total_screen_duration_s=58.0,
    )


def _points_of(html_path: Path, css_class: str) -> list[str]:
    html = html_path.read_text(encoding="utf-8")
    found = re.search(rf'class="{css_class}" points="([^"]*)"', html)
    return found.group(1).split() if found else []


def test_a_chapter_on_the_clock_is_cut_where_the_track_was(tmp_path: Path) -> None:
    write_chapter_cards(
        _clock_plan(), tmp_path, route_points=_route(), runner=_recording_runner([])
    )
    cards = tmp_path / "story-cards"

    whole = _points_of(cards / "card-002.html", "route")
    first = _points_of(cards / "card-002.html", "here")
    last = _points_of(cards / "card-004.html", "here")
    assert first[0] == whole[0] and len(first) == 51, "0 to 50 minutes is 51 points"
    assert last[0] == whole[70] and last[-1] == whole[-1], "70 minutes to the end"


def test_a_halt_is_a_dot_on_the_route_and_holds_still(tmp_path: Path) -> None:
    rasters = write_chapter_cards(
        _clock_plan(), tmp_path, route_points=_route(), runner=_recording_runner([])
    )
    cards = tmp_path / "story-cards"

    halt_html = (cards / "card-003.html").read_text(encoding="utf-8")
    assert '<circle class="mark"' in halt_html
    assert 'class="here"' not in halt_html, "a halt has no stretch to draw"
    assert not rasters[2].is_sequence and not list(cards.glob("card-003-f*.html"))
    whole = _points_of(cards / "card-003.html", "route")
    x, y = re.search(r'cx="([^"]+)" cy="([^"]+)"', halt_html).groups()
    assert f"{x},{y}" == whole[60], "the dot sits where the track was mid-halt"


def test_a_halt_off_the_clock_marks_the_middle_of_its_share(tmp_path: Path) -> None:
    beats = list(_plan().beats)
    beats[4] = _card("ここで休む", GapCharacter.HALT, JourneyGapKind.BETWEEN_CLIPS, 6.0)
    plan = JourneyStoryPlan(
        beats=tuple(beats),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=24.0,
        total_screen_duration_s=52.0,
    )
    write_chapter_cards(plan, tmp_path, route_points=_route(), runner=_recording_runner([]))

    halt_html = (tmp_path / "story-cards" / "card-003.html").read_text(encoding="utf-8")
    whole = _points_of(tmp_path / "story-cards" / "card-003.html", "route")
    x, y = re.search(r'cx="([^"]+)" cy="([^"]+)"', halt_html).groups()
    assert f"{x},{y}" == whole[149], "the second of two chapters: the middle of 100..199"


def test_a_plan_where_one_chapter_lacks_its_clock_falls_back_to_positions(tmp_path: Path) -> None:
    beats = list(_clock_plan().beats)
    beats[5] = _card("海沿い", GapCharacter.COAST, JourneyGapKind.BETWEEN_CLIPS, 6.0)
    plan = JourneyStoryPlan(
        beats=tuple(beats),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=24.0,
        total_screen_duration_s=58.0,
    )
    write_chapter_cards(plan, tmp_path, route_points=_route(), runner=_recording_runner([]))

    first = _points_of(tmp_path / "story-cards" / "card-002.html", "here")
    assert len(first) == 68, "three chapters share 200 points: 0..67"


def test_the_headline_and_the_close_draw_the_map_large(tmp_path: Path) -> None:
    write_chapter_cards(
        _clock_plan(), tmp_path, route_points=_route(), runner=_recording_runner([])
    )
    cards = tmp_path / "story-cards"

    assert 'class="map map-wide"' in (cards / "card-001.html").read_text(encoding="utf-8")
    assert 'class="map map-wide"' in (cards / "card-005.html").read_text(encoding="utf-8")
    assert 'class="map"' in (cards / "card-002.html").read_text(encoding="utf-8")


def test_stale_frames_from_an_earlier_drawing_are_removed(tmp_path: Path) -> None:
    cards = tmp_path / "story-cards"
    cards.mkdir()
    stale = cards / "card-003-f099.html.png"
    stale.write_bytes(b"old")

    write_chapter_cards(
        _clock_plan(), tmp_path, route_points=_route(), runner=_recording_runner([])
    )

    assert not stale.exists(), "a halt that used to animate must not keep its old frames"
