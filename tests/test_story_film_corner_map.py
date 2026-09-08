"""Synthetic-fixture tests for the small map of where the ride is, on every clip (E-9).

Held: each footage beat gets one still with the route, the part ridden so
far, and a dot at the clip's ride time; a beat with no known ride time gets
none; the film takes the map as an extra input scaled into the top-left
corner for the whole clip, under the chapter's title when there is one.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from app.chapter_card import ChapterCardError, build_position_map_html, route_map_svg
from app.story_film import (
    CORNER_MAP_HEIGHT_SHARE,
    CORNER_MAP_MARGIN_SHARE,
    CardRaster,
    LowerThirdLayer,
    StoryFilmSegment,
    build_story_film_command,
    build_story_film_segments,
    write_chapter_cards,
    write_position_maps,
)
from app.story_timeline import StoryBeatKind
from tests.test_story_film_lower_third import _sources, _titled_plan
from tests.test_story_film_moving_route import _T0, _recording_runner, _route


def _ride_times() -> dict[str, object]:
    # The route has a point a minute for 200 minutes; w-1 begins 50 min in.
    return {
        "w-open": _T0 + timedelta(minutes=10),
        "w-1": _T0 + timedelta(minutes=50),
        "w-2": _T0 + timedelta(minutes=120),
    }


def test_every_clip_with_a_known_ride_time_gets_a_map_with_a_dot(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    write_chapter_cards(
        _titled_plan(), tmp_path, route_points=_route(), runner=_recording_runner(calls)
    )

    maps = write_position_maps(
        _titled_plan(),
        tmp_path,
        route_points=_route(),
        ride_times=_ride_times(),
        runner=_recording_runner(calls),
    )

    assert set(maps) == {"w-open", "w-1", "w-2"}
    assert all(png.is_file() for png in maps.values())
    page = (tmp_path / "story-cards" / "pos-002.html").read_text(encoding="utf-8")
    assert '<circle class="mark"' in page and 'class="here"' in page
    ridden = re.search(r'class="here" points="([^"]*)"', page).group(1).split()
    # w-1 starts 50 min in; the middle of the 8 s clip is the first point at or after it, minute 51.
    assert len(ridden) == 52
    assert len(calls) == 2, "the cards in one call, the maps in one call"


def test_a_clip_whose_ride_time_is_unknown_gets_no_map(tmp_path: Path) -> None:
    maps = write_position_maps(
        _titled_plan(),
        tmp_path,
        route_points=_route(),
        ride_times={"w-1": _T0 + timedelta(minutes=50)},
        runner=_recording_runner([]),
    )

    assert set(maps) == {"w-1"}


def test_the_clips_own_offset_moves_the_dot(tmp_path: Path) -> None:
    from app.agents import StoryOutputLanguage
    from app.story_package import JourneyStoryPlan, StoryPlanBeat

    plan = JourneyStoryPlan(
        beats=(StoryPlanBeat(StoryBeatKind.FOOTAGE, 6.0, event_id="w-1", source_offset_s=360.0),),
        output_language=StoryOutputLanguage.JAPANESE,
        footage_screen_duration_s=6.0,
        total_screen_duration_s=6.0,
    )
    write_position_maps(
        plan,
        tmp_path,
        route_points=_route(),
        ride_times={"w-1": _T0 + timedelta(minutes=50)},
        runner=_recording_runner([]),
    )

    page = (tmp_path / "story-cards" / "pos-001.html").read_text(encoding="utf-8")
    ridden = re.search(r'class="here" points="([^"]*)"', page).group(1).split()
    assert len(ridden) == 58, "50 min in, plus a 6 min offset and half a 6 s clip: minute 57"


def test_segments_carry_the_map_and_only_footage_may(tmp_path: Path) -> None:
    still = tmp_path / "still.png"
    still.write_bytes(b"\x89PNG")
    maps = {"w-1": tmp_path / "pos-002.html.png"}
    rasters = (
        CardRaster(still=still),
        CardRaster(still=still, lower_third=True),
        CardRaster(still=still),
    )

    segments = build_story_film_segments(
        _titled_plan(), rasters, _sources(tmp_path), position_maps=maps
    )

    by_event = {s.input_path.name: s for s in segments if s.kind is StoryBeatKind.FOOTAGE}
    assert by_event["w-1.mp4"].corner_map == maps["w-1"]
    assert by_event["w-2.mp4"].corner_map is None
    with pytest.raises(ValueError, match="only footage"):
        StoryFilmSegment(StoryBeatKind.GAP_CARD, still, 6.0, corner_map=still)


def test_the_map_is_an_extra_input_scaled_into_the_corner_under_the_title(tmp_path: Path) -> None:
    corner = tmp_path / "pos-001.html.png"
    layer = LowerThirdLayer(input_path=tmp_path / "card-002.html.png", duration_s=5.0)
    segments = (
        StoryFilmSegment(
            StoryBeatKind.FOOTAGE,
            tmp_path / "w1.mp4",
            8.0,
            source_start_s=30.0,
            lower_third=layer,
            corner_map=corner,
        ),
        StoryFilmSegment(StoryBeatKind.GAP_CARD, tmp_path / "close.png", 6.0),
    )

    command = build_story_film_command(segments, tmp_path / "out.mp4", overwrite=True)
    joined = " ".join(command)
    graph = command[command.index("-filter_complex") + 1]
    chains = graph.split(";")

    assert f"-loop 1 -t 8.000 -i {corner}" in joined, "held for the whole clip"
    assert joined.index(str(corner)) < joined.index(str(layer.input_path)), "corner map, then title"
    side = round(1080 * CORNER_MAP_HEIGHT_SHARE)
    margin = round(1080 * CORNER_MAP_MARGIN_SHARE)
    assert f"[1:v:0]scale={side}:{side},fps=30,format=yuv420p[m0]" in chains
    assert f"[v0][m0]overlay={margin}:{margin}:eof_action=pass:repeatlast=0[c0]" in chains
    assert any(c.startswith("[c0][s0]overlay") for c in chains), (
        "the title goes over the corner map"
    )
    assert chains[-1].startswith("[w0][v1]concat=n=2")
    assert re.search(r"\[3:v:0\][^;]*\[v1\]", graph), "the close is input 3, after map and title"


def test_a_clip_without_a_title_still_gets_its_corner_map(tmp_path: Path) -> None:
    corner = tmp_path / "pos-001.html.png"
    segments = (
        StoryFilmSegment(StoryBeatKind.FOOTAGE, tmp_path / "w1.mp4", 6.0, corner_map=corner),
    )

    command = build_story_film_command(segments, tmp_path / "out.mp4", overwrite=True)
    graph = command[command.index("-filter_complex") + 1]

    assert graph.endswith("[c0]concat=n=1:v=1:a=0[v]")


def test_the_position_page_is_the_panel_itself() -> None:
    svg = route_map_svg(_route(), highlight_from_index=0, highlight_to_index=20, mark_index=20)
    html = build_position_map_html(svg)

    assert "border" in html and '<circle class="mark"' in html
    assert "src=" not in html and "href=" not in html
    with pytest.raises(ChapterCardError):
        build_position_map_html("")


def test_cards_and_corner_maps_are_drawn_on_the_map_when_one_is_given(tmp_path: Path) -> None:
    from app.map_background import MapBackground, frame_for

    png = tmp_path / "m.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    background = MapBackground.from_file(frame_for(_route()), png)

    write_chapter_cards(
        _titled_plan(),
        tmp_path,
        route_points=_route(),
        runner=_recording_runner([]),
        background=background,
    )
    write_position_maps(
        _titled_plan(),
        tmp_path,
        route_points=_route(),
        ride_times=_ride_times(),
        runner=_recording_runner([]),
        background=background,
    )

    cards = tmp_path / "story-cards"
    assert '<image href="data:image/png;base64,' in (cards / "card-001.html").read_text(
        encoding="utf-8"
    )
    assert '<image href="data:image/png;base64,' in (cards / "pos-001.html").read_text(
        encoding="utf-8"
    )
