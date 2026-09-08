"""Synthetic-fixture tests for chapter card layout and the drawn route."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.chapter_card import (
    ChapterCardError,
    build_chapter_card_html,
    build_lower_third_html,
    route_map_svg,
)
from app.contracts import RoutePoint
from app.gap_chapters import GapChapterCard, GapCharacter
from app.journey_gaps import JourneyGapKind

_START = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _card(title: str = "旅の始まり", body: str = "15分 · 1.4km") -> GapChapterCard:
    return GapChapterCard(
        kind=JourneyGapKind.BEFORE_FIRST_CLIP,
        character=GapCharacter.DEPARTURE,
        title=title,
        body=body,
        screen_duration_s=12.0,
    )


def _points(count: int = 10, *, moving: bool = True) -> tuple[RoutePoint, ...]:
    # A north-east heading ride; the step keeps even long tracks in valid range.
    step = 0.05 / max(1, count)
    return tuple(
        RoutePoint(
            timestamp=_START + timedelta(seconds=60 * index),
            latitude=35.0 + (step * index if moving else 0.0),
            longitude=139.0 + (2 * step * index if moving else 0.0),
            elevation_m=100.0 + index,
            distance_from_start_m=1_000.0 * index,
            speed_mps=20.0,
        )
        for index in range(count)
    )


def test_card_html_is_self_contained() -> None:
    html = build_chapter_card_html(_card())

    assert html.startswith("<!doctype html>")
    # Nothing to fetch: rasterising the page cannot reach the network.
    for external in ("<script", "src=", "href=", "@import", "url("):
        assert external not in html


def test_card_html_carries_the_title_and_body() -> None:
    html = build_chapter_card_html(_card(title="登りが続く", body="1時間17分 · 91.8km"))

    assert "登りが続く" in html
    assert "1時間17分 · 91.8km" in html


def test_card_text_is_escaped() -> None:
    html = build_chapter_card_html(_card(title="<script>alert(1)</script>"))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_card_without_text_is_refused() -> None:
    card = _card()
    object.__setattr__(card, "title", "")
    with pytest.raises(ChapterCardError, match="title and a body"):
        build_chapter_card_html(card)


def test_the_map_is_included_only_when_given() -> None:
    assert "<svg" not in build_chapter_card_html(_card())
    assert "<svg" in build_chapter_card_html(_card(), route_map_svg=route_map_svg(_points()))


def test_route_map_draws_the_whole_ride() -> None:
    svg = route_map_svg(_points(count=6))

    assert svg.startswith("<svg")
    assert 'class="route"' in svg
    coordinates = re.search(r'class="route" points="([^"]+)"', svg).group(1)
    assert len(coordinates.split(" ")) == 6


def test_route_map_holds_no_coordinate_on_earth() -> None:
    """Only the ride's shape survives; its position does not."""
    svg = route_map_svg(_points())

    assert "35." not in svg
    assert "139." not in svg
    for word in ("latitude", "longitude", "lat", "lon"):
        assert word not in svg.lower()


def test_drawn_points_stay_inside_the_view_box() -> None:
    svg = route_map_svg(_points(count=40), view_width=560, view_height=160, padding=12)

    for pair in re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" "):
        x, y = (float(value) for value in pair.split(","))
        assert 12 - 0.05 <= x <= 560 - 12 + 0.05
        assert 12 - 0.05 <= y <= 160 - 12 + 0.05


def test_north_is_up() -> None:
    """A ride heading north must draw upward, so its y must decrease."""
    svg = route_map_svg(_points(count=5))

    pairs = re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" ")
    ys = [float(pair.split(",")[1]) for pair in pairs]
    assert ys[0] > ys[-1]


def test_a_highlighted_stretch_is_drawn_over_the_route() -> None:
    svg = route_map_svg(_points(count=20), highlight_from_index=5, highlight_to_index=12)

    assert 'class="here"' in svg
    assert svg.index('class="route"') < svg.index('class="here"')
    highlighted = re.search(r'class="here" points="([^"]+)"', svg).group(1)
    assert len(highlighted.split(" ")) == 8


def test_a_highlight_outside_the_route_is_refused() -> None:
    with pytest.raises(ChapterCardError, match="inside the route"):
        route_map_svg(_points(count=10), highlight_from_index=2, highlight_to_index=99)
    with pytest.raises(ChapterCardError, match="inside the route"):
        route_map_svg(_points(count=10), highlight_from_index=8, highlight_to_index=3)


def test_a_long_track_is_thinned_but_keeps_both_ends() -> None:
    points = _points(count=5_000)

    svg = route_map_svg(points)

    drawn = re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" ")
    assert len(drawn) <= 401
    # Both ends of the ride are still drawn, so the shape is not clipped.
    xs = [float(pair.split(",")[0]) for pair in drawn]
    assert min(xs) == pytest.approx(xs[0], abs=0.2)
    assert max(xs) == pytest.approx(xs[-1], abs=0.2)


def test_a_highlight_survives_thinning() -> None:
    svg = route_map_svg(_points(count=5_000), highlight_from_index=2_000, highlight_to_index=3_000)

    assert 'class="here"' in svg
    assert len(re.search(r'class="here" points="([^"]+)"', svg).group(1).split(" ")) >= 2


def test_a_route_that_never_moves_is_refused() -> None:
    with pytest.raises(ChapterCardError, match="route that moves"):
        route_map_svg(_points(count=5, moving=False))


def test_too_few_points_or_no_room_is_refused() -> None:
    with pytest.raises(ChapterCardError, match="at least two points"):
        route_map_svg(_points(count=1))
    with pytest.raises(ChapterCardError, match="room inside its padding"):
        route_map_svg(_points(), view_width=20, view_height=160, padding=12)


def test_a_mark_is_a_dot_where_the_route_was() -> None:
    points = _points(count=20)
    svg = route_map_svg(points, mark_index=len(points) // 2)

    assert '<circle class="mark"' in svg
    x, y = (float(v) for v in re.search(r'cx="([^"]+)" cy="([^"]+)"', svg).groups())
    assert 0 <= x <= 320 and 0 <= y <= 320
    assert 'class="here"' not in svg


def test_a_mark_outside_the_route_is_refused() -> None:
    points = _points(count=20)
    with pytest.raises(ChapterCardError, match="mark"):
        route_map_svg(points, mark_index=len(points))


def test_a_wide_map_says_so_in_its_class() -> None:
    points = _points(count=20)
    assert 'class="map map-wide"' in route_map_svg(points, wide=True)
    assert 'class="map"' in route_map_svg(points)


def test_a_lower_third_page_fits_its_text_and_stands_alone() -> None:
    card = _card(title="長い下り", body="出発から3時間06分 · 142.0km · 海抜815m → 67m")
    html = build_lower_third_html(card, route_map_svg=route_map_svg(_points(count=20)))

    assert 'class="strip"' in html and 'class="band"' in html
    assert "長い下り" in html
    assert "出発から3時間06分 · 142.0km" in html and "海抜" not in html
    assert "<svg" in html
    assert "src=" not in html and "href=" not in html and "<script" not in html


def test_a_lower_third_body_does_not_repeat_its_title() -> None:
    html = build_lower_third_html(_card(title="出発", body="出発 · 112.3km"))

    assert 'class="body">112.3km<' in html
    assert html.count("出発") == 1


def test_a_lower_third_whose_body_is_only_its_title_keeps_something_to_say() -> None:
    html = build_lower_third_html(_card(title="出発", body="出発"))

    assert 'class="body">出発<' in html


def test_a_card_without_a_label_shows_no_label_div() -> None:
    assert '<div class="label">' not in build_chapter_card_html(_card())


def test_a_lower_third_without_text_is_refused() -> None:
    card = _card()
    object.__setattr__(card, "body", "")
    with pytest.raises(ChapterCardError, match="title and a body"):
        build_lower_third_html(card)


def test_a_lower_third_without_a_map_has_no_svg() -> None:
    assert "<svg" not in build_lower_third_html(_card())
    assert "<svg" in build_lower_third_html(_card(), route_map_svg=route_map_svg(_points()))


def test_a_route_exactly_at_the_thinning_limit_is_kept_whole() -> None:
    points = _points(count=400)

    svg = route_map_svg(points)

    drawn = re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" ")
    assert len(drawn) == 400


def test_one_point_past_the_thinning_limit_triggers_thinning() -> None:
    points = _points(count=401)

    svg = route_map_svg(points)

    drawn = re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" ")
    assert len(drawn) < 401


def test_a_mark_stays_at_its_relative_place_after_thinning() -> None:
    points = _points(count=5_000)

    svg = route_map_svg(points, mark_index=len(points) - 1)

    x, y = (float(v) for v in re.search(r'cx="([^"]+)" cy="([^"]+)"', svg).groups())
    # The last point of the route is also the last point kept by thinning.
    last_route_point = re.search(r'class="route" points="([^"]+)"', svg).group(1).split(" ")[-1]
    assert f"{x:.1f},{y:.1f}" == last_route_point


def test_a_marks_radius_is_the_one_given() -> None:
    svg = route_map_svg(_points(count=10), mark_index=5, mark_radius=25)

    assert '<circle class="mark" cx=' in svg
    assert re.search(r'<circle class="mark"[^/]* r="25"', svg)


def test_a_highlight_of_a_single_point_still_draws_a_line() -> None:
    svg = route_map_svg(_points(count=20), highlight_from_index=5, highlight_to_index=5)

    highlighted = re.search(r'class="here" points="([^"]+)"', svg).group(1).split(" ")
    assert len(highlighted) == 2


def test_a_card_with_a_day_label_shows_it_above_the_title() -> None:
    from app.chapter_card import build_chapter_card_html
    from app.gap_chapters import GapChapterCard, GapCharacter
    from app.journey_gaps import JourneyGapKind

    card = GapChapterCard(
        kind=JourneyGapKind.BETWEEN_CLIPS,
        character=GapCharacter.LINK,
        title="Eastholm → Rimuka",
        body="269km · 4時間10分\n登り1600m",
        screen_duration_s=6.0,
        label="Day 1",
    )

    page = build_chapter_card_html(card)

    assert '<div class="label">Day 1</div>' in page
    assert page.index("Day 1") < page.index("Eastholm → Rimuka")
    assert "269km · 4時間10分<br>登り1600m" in page
