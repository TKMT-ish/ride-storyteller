"""Synthetic tests for the map behind the route figures (E-10). Nothing here reaches the network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import RoutePoint
from app.map_background import (
    DARK_STYLE,
    MAP_SIZE_PX,
    MAX_ZOOM,
    ROUTE_FIT_SHARE,
    UNLABELLED_STYLE,
    MapBackgroundError,
    MapFrame,
    frame_for,
    map_background,
    static_map_url,
)

_T0 = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)


def _points(count: int = 50, *, span: float = 0.5) -> tuple[RoutePoint, ...]:
    return tuple(
        RoutePoint(
            timestamp=_T0 + timedelta(minutes=i),
            latitude=-43.0 + span * i / count,
            longitude=170.0 + span * i / count,
            elevation_m=100.0,
            distance_from_start_m=1000.0 * i,
            speed_mps=10.0,
        )
        for i in range(count)
    )


def test_the_frame_fits_the_whole_ride_with_room_around_it() -> None:
    points = _points()
    frame = frame_for(points)

    corners = [frame.project(p.latitude, p.longitude) for p in points]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    margin = frame.pixels * (1 - 0.84) / 2 * 0.9
    assert min(xs) >= margin and max(xs) <= frame.pixels - margin
    assert min(ys) >= margin and max(ys) <= frame.pixels - margin
    assert frame.zoom > 0


def test_the_centre_projects_to_the_middle_and_north_is_up() -> None:
    frame = MapFrame(-43.0, 170.0, 8)

    assert frame.project(-43.0, 170.0) == (frame.pixels / 2, frame.pixels / 2)
    _, further_north = frame.project(-42.0, 170.0)
    assert further_north < frame.pixels / 2


def test_a_wider_ride_gets_a_smaller_zoom() -> None:
    assert frame_for(_points(span=2.0)).zoom < frame_for(_points(span=0.2)).zoom


def test_the_request_carries_centre_zoom_and_style_but_never_the_track() -> None:
    frame = frame_for(_points())
    url = static_map_url(frame, style=DARK_STYLE, key="k")

    assert "center=" in url and "zoom=" in url and f"size={MAP_SIZE_PX}x{MAP_SIZE_PX}" in url
    assert "path=" not in url and "markers=" not in url
    assert url.count("style=") == len(DARK_STYLE)
    assert "labels%7Cvisibility%3Aoff" in static_map_url(frame, style=UNLABELLED_STYLE, key="k")
    with pytest.raises(MapBackgroundError, match="key"):
        static_map_url(frame, style=DARK_STYLE, key="")


def test_the_request_language_defaults_to_japanese_but_can_be_overridden() -> None:
    frame = frame_for(_points())

    assert "language=ja" in static_map_url(frame, style=DARK_STYLE, key="k")
    assert "language=en" in static_map_url(frame, style=DARK_STYLE, key="k", language="en")


def test_the_image_is_fetched_once_and_kept_in_the_package(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b"\x89PNG\r\n\x1a\nfake"

    frame, path = map_background(tmp_path, _points(), key="k", fetch=fetch)
    again, same = map_background(tmp_path, _points(), key="k", fetch=fetch)

    assert path.is_file() and path.parent == tmp_path / "map-background"
    assert same == path and again == frame
    assert len(calls) == 1, "the second call reads the cache"
    assert "key=k" in calls[0]


def test_a_different_style_is_a_different_image(tmp_path: Path) -> None:
    fetch = lambda url: b"\x89PNG\r\n\x1a\n"  # noqa: E731

    _, dark = map_background(tmp_path, _points(), key="k", fetch=fetch)
    _, bare = map_background(tmp_path, _points(), style=UNLABELLED_STYLE, key="k", fetch=fetch)

    assert dark != bare


def test_the_cache_key_is_stable_and_changes_with_every_input_that_reaches_the_image() -> None:
    frame = MapFrame(-43.0, 170.0, 8)
    other_zoom = MapFrame(-43.0, 170.0, 9)
    other_size = MapFrame(-43.0, 170.0, 8, size_px=320)
    other_scale = MapFrame(-43.0, 170.0, 8, scale=1)

    assert frame.key(DARK_STYLE) == frame.key(DARK_STYLE), "same frame and style, same key"
    assert frame.key(DARK_STYLE) != frame.key(UNLABELLED_STYLE)
    assert frame.key(DARK_STYLE) != other_zoom.key(DARK_STYLE)
    assert frame.key(DARK_STYLE) != other_size.key(DARK_STYLE)
    assert frame.key(DARK_STYLE) != other_scale.key(DARK_STYLE)


def test_something_that_is_not_a_png_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MapBackgroundError, match="PNG"):
        map_background(tmp_path, _points(), key="k", fetch=lambda url: b"<html>no</html>")
    assert not list((tmp_path / "map-background").glob("*.png"))


def test_a_zero_byte_cache_entry_is_not_trusted(tmp_path: Path) -> None:
    """A crashed fetch can leave an empty file behind; that is not a cache hit."""
    frame = frame_for(_points())
    cache = tmp_path / "map-background"
    cache.mkdir()
    (cache / f"map-{frame.key(DARK_STYLE)}.png").touch()
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return _fake_png()

    _, path = map_background(tmp_path, _points(), key="k", fetch=fetch)

    assert len(calls) == 1, "the empty placeholder must not short-circuit the fetch"
    assert path.stat().st_size > 0


def test_a_symlinked_cache_directory_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "map-background").symlink_to(elsewhere)

    with pytest.raises(MapBackgroundError, match="unsafe"):
        map_background(tmp_path, _points(), key="k", fetch=lambda url: _fake_png())


def test_frames_refuse_nonsense() -> None:
    with pytest.raises(MapBackgroundError):
        MapFrame(95.0, 0.0, 5)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, 30)
    with pytest.raises(MapBackgroundError):
        frame_for(_points(count=1))


def test_frame_bounds_are_inclusive_at_the_pole_and_the_date_line() -> None:
    """`-85..85` and `-180..180` are the edges of the map, not defects."""
    MapFrame(85.0, 180.0, 0)
    MapFrame(-85.0, -180.0, MAX_ZOOM)
    with pytest.raises(MapBackgroundError):
        MapFrame(85.0 + 1e-9, 0.0, 5)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, -180.0 - 1e-9, 5)


def test_frame_zoom_bounds_are_inclusive() -> None:
    MapFrame(0.0, 0.0, 0)
    MapFrame(0.0, 0.0, MAX_ZOOM)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, -1)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, MAX_ZOOM + 1)


def test_frame_size_and_scale_reject_non_positive_or_unsupported_values() -> None:
    MapFrame(0.0, 0.0, 5, size_px=1, scale=1)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, 5, size_px=0)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, 5, size_px=-1)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, 5, scale=0)
    with pytest.raises(MapBackgroundError):
        MapFrame(0.0, 0.0, 5, scale=3)


def _point(latitude: float, longitude: float, index: int) -> RoutePoint:
    return RoutePoint(
        timestamp=_T0 + timedelta(minutes=index),
        latitude=latitude,
        longitude=longitude,
        elevation_m=100.0,
        distance_from_start_m=1000.0 * index,
        speed_mps=10.0,
    )


def test_frame_for_zoom_threshold_is_inclusive_at_the_exact_pixel_width() -> None:
    """`frame_for` keeps a candidate zoom when the fit is `<=` the share, not `<`.

    A span sized so the world-pixel width at zoom 8 lands exactly on
    `MAP_SIZE_PX * ROUTE_FIT_SHARE` still picks zoom 8; a hair wider drops to
    the previous zoom, the same one-step-either-side shape the other boundary
    hardening units in this codebase use.
    """
    target_zoom = 8
    threshold_px = MAP_SIZE_PX * ROUTE_FIT_SHARE
    lon_span = threshold_px * 360.0 / (256.0 * 2**target_zoom)
    at_the_edge = (_point(0.0, 170.0, 0), _point(0.0, 170.0 + lon_span, 1))
    a_hair_wider = (_point(0.0, 170.0, 0), _point(0.0, 170.0 + lon_span + 1e-6, 1))

    assert frame_for(at_the_edge).zoom == target_zoom
    assert frame_for(a_hair_wider).zoom == target_zoom - 1


# --- drawing on the map, and doing without one -------------------------------------------------


def _fake_png() -> bytes:
    return b"\x89PNG\r\n\x1a\nfake"


def test_a_background_is_the_frame_and_a_png_data_uri(tmp_path: Path) -> None:
    from app.map_background import MapBackground

    png = tmp_path / "m.png"
    png.write_bytes(_fake_png())
    frame = MapFrame(-43.0, 170.0, 8)

    background = MapBackground.from_file(frame, png)

    assert background.frame == frame
    assert background.data_uri.startswith("data:image/png;base64,")
    with pytest.raises(MapBackgroundError, match="PNG"):
        MapBackground(frame, "data:text/plain,hello")


def test_the_route_is_drawn_over_the_map_in_the_maps_own_pixels(tmp_path: Path) -> None:
    from app.chapter_card import route_map_svg
    from app.map_background import MapBackground

    png = tmp_path / "m.png"
    png.write_bytes(_fake_png())
    points = _points(count=20)
    background = MapBackground.from_file(frame_for(points), png)

    svg = route_map_svg(
        points, highlight_from_index=0, highlight_to_index=5, mark_index=5, background=background
    )

    size = background.frame.pixels
    assert f'viewBox="0 0 {size} {size}"' in svg
    assert '<image href="data:image/png;base64,' in svg
    assert 'vector-effect="non-scaling-stroke"' in svg
    assert 'class="map on-map"' in svg, "so each page sizes its strokes for its own scale"
    first = svg.split('class="route" points="')[1].split()[0]
    x, y = background.frame.project(points[0].latitude, points[0].longitude)
    assert first == f"{x:.1f},{y:.1f}", "placed by the map's projection, not by fitting"
    assert '<circle class="mark"' in svg


def test_the_style_choice_has_three_names_and_none_fetches_nothing(tmp_path: Path) -> None:
    from app.map_background import MAP_STYLES, background_or_none, style_named

    assert set(MAP_STYLES) == {"labels", "plain"}
    assert style_named("none") == ()
    with pytest.raises(MapBackgroundError, match="unknown"):
        style_named("sepia")
    calls: list[str] = []
    assert (
        background_or_none(
            tmp_path,
            _points(),
            style_name="none",
            key="k",
            fetch=lambda u: calls.append(u) or _fake_png(),
        )
        is None
    )
    assert calls == []


def test_chosen_style_name_falls_back_through_env_then_dotenv_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.map_background as map_background_module
    from app.map_background import DEFAULT_MAP_STYLE, MAP_STYLE_ENV, chosen_style_name

    monkeypatch.delenv(MAP_STYLE_ENV, raising=False)
    monkeypatch.setattr(map_background_module, "load_local_environment", lambda: {})
    assert chosen_style_name() == DEFAULT_MAP_STYLE

    monkeypatch.setattr(
        map_background_module, "load_local_environment", lambda: {MAP_STYLE_ENV: "plain"}
    )
    assert chosen_style_name() == "plain", "no process env, so the .env file is used"

    monkeypatch.setenv(MAP_STYLE_ENV, "  LABELS  ")
    assert chosen_style_name() == "labels", "process env wins, and is trimmed and lowercased"

    monkeypatch.setenv(MAP_STYLE_ENV, "")
    assert chosen_style_name() == DEFAULT_MAP_STYLE, (
        "an env var set but empty is not treated as absent, so the .env value below it "
        "is never consulted -- it falls straight through to the default"
    )


def test_without_a_service_the_film_draws_on_black(tmp_path: Path) -> None:
    from app.map_background import background_or_none

    def refused(url: str) -> bytes:
        raise MapBackgroundError("the map service refused the request")

    assert (
        background_or_none(tmp_path, _points(), style_name="labels", key="k", fetch=refused) is None
    )
    assert (
        background_or_none(tmp_path, _points(), style_name="labels", key="", fetch=refused) is None
    )
    drawn = background_or_none(
        tmp_path, _points(), style_name="plain", key="k", fetch=lambda u: _fake_png()
    )
    assert drawn is not None and drawn.frame.zoom > 0
