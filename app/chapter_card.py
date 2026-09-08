"""Draw the card the viewer reads while the film crosses an unfilmed stretch.

Gate 3 of docs/completion-roadmap-ja.md. `app.gap_chapters` decided what each
card says and how long it is held; this decides what it looks like, as an
HTML page that macOS can rasterise with no third-party library. The project
ships with no runtime dependencies and the installed FFmpeg has neither
`drawtext` nor `subtitles` (built without freetype and libass), so laying the
card out in HTML and letting the system render it is what keeps Japanese
text, and a drawn route, possible at all here.

The card also answers Gate 3's map requirement. A gap card carries the whole
ride as a faint line with the stretch it stands for picked out on top, so the
viewer sees not just that time passed but *where* along the journey it
passed. The line is normalised into the drawing's own box: it keeps the
route's shape and loses its position on Earth, and it never leaves the
private film.

The font stack names macOS's Japanese faces first and Noto's after them.
A Linux container must actually install a CJK font: without one the stack
falls through to a Latin face and every Japanese character on the card
renders as an empty box. The layout would look correct and the words would
be gone.

Everything here is a pure function returning a string. Rasterising is a
separate step, so the layout can be tested without invoking any external
tool.
"""

from __future__ import annotations

import math
from html import escape

from app.contracts import RoutePoint
from app.gap_chapters import GapChapterCard
from app.lower_third_text import (
    BODY_SEPARATOR,
    MAX_BODY_CHARS,
    fit_lower_third_text,
    fit_title,
)
from app.map_background import MapBackground

# Quick Look renders HTML into a square, so the page is authored square and
# the film's 16:9 frame is taken from the middle of it. Sizes are in viewport
# units for that reason: the page must centre itself in whatever viewport the
# renderer chooses, not in a width we assumed.
CARD_ASPECT_NUMERATOR = 16
CARD_ASPECT_DENOMINATOR = 9

# More points than this in one drawing costs bytes without changing the shape.
_MAX_MAP_POINTS = 400

# The dot that stands for a halt, in view-box units (the route is 5 wide).
_MARK_RADIUS = 9

_CARD_STYLE = """
html,body{margin:0;padding:0}
body{width:100vw;height:100vh;background:#11131a;color:#f4f4f2;
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN",
"Noto Sans CJK JP","Noto Sans JP","Helvetica Neue",Helvetica,Arial,sans-serif;
display:flex;flex-direction:column;justify-content:center;align-items:center;
text-align:center;overflow:hidden}
.label{font-size:2.4vw;margin:0 0 1.4vw;letter-spacing:.2em;color:#9ed0ff;font-weight:600}
.title{font-size:6.0vw;margin:0 0 2.2vw;letter-spacing:.06em;font-weight:600;
line-height:1.15;max-width:90vw}
.body{font-size:2.6vw;margin:0;color:#a8b0c0;letter-spacing:.04em;
line-height:1.4}
.map{width:19vw;height:19vw;margin-top:2.6vw}
.map-wide{width:30vw;height:30vw}
.mark{fill:#5aa9e6;stroke:#11131a;stroke-width:3}
.on-map .route{stroke:#aeb7c8;stroke-width:6}
.on-map .here{stroke:#4fb3ff;stroke-width:9}
.on-map .mark{stroke:#11131a;stroke-width:4}
.route{fill:none;stroke:#2f3646;stroke-width:5;stroke-linejoin:round;
stroke-linecap:round}
.here{fill:none;stroke:#5aa9e6;stroke-width:7;stroke-linejoin:round;
stroke-linecap:round}
"""


# The lower third takes this share of the film's frame from the bottom: 240 of
# 1080 lines. The film crops the drawn page to exactly this strip, so the
# layout below and the crop must agree.
LOWER_THIRD_HEIGHT_SHARE = 2 / 9

# The page is drawn square and the film's 16:9 band is its middle; the strip
# sits at the bottom of that band. In vw of the square page:
_BAND_TOP_VW = (100 - 100 * CARD_ASPECT_DENOMINATOR / CARD_ASPECT_NUMERATOR) / 2
_BAND_HEIGHT_VW = 100 * CARD_ASPECT_DENOMINATOR / CARD_ASPECT_NUMERATOR
_STRIP_HEIGHT_VW = _BAND_HEIGHT_VW * LOWER_THIRD_HEIGHT_SHARE

# Drawn on black and laid over the footage with brightness as opacity, so the
# text is white and the route brighter than on a card; black contributes
# nothing. The darkening under it is the film's own translucent strip.
_LOWER_THIRD_STYLE = f"""
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN",
"Noto Sans CJK JP","Noto Sans JP","Helvetica Neue",Helvetica,Arial,sans-serif;
overflow:hidden}}
.band{{position:absolute;left:0;top:{_BAND_TOP_VW:.4f}vw;width:100vw;height:{_BAND_HEIGHT_VW:.4f}vw}}
.strip{{position:absolute;left:0;bottom:0;width:100vw;height:{_STRIP_HEIGHT_VW:.4f}vw;
box-sizing:border-box;padding:0 4vw;display:flex;align-items:center;
justify-content:space-between}}
.text{{display:flex;flex-direction:column;gap:.9vw;text-align:left}}
.title{{font-size:3.6vw;font-weight:700;letter-spacing:.06em;line-height:1.1;margin:0}}
.body{{font-size:1.9vw;color:#d7dde9;letter-spacing:.04em;margin:0}}
.map{{width:10.4vw;height:10.4vw;flex:none}}
.route{{fill:none;stroke:#b8c0d0;stroke-width:11;stroke-linejoin:round;
stroke-linecap:round}}
.here{{fill:none;stroke:#9ed0ff;stroke-width:15;stroke-linejoin:round;
stroke-linecap:round}}
.mark{{fill:#9ed0ff;stroke:#000;stroke-width:3}}
"""


# The corner map on every clip (E-9): the whole page is the panel, drawn
# square and scaled down by the film, so its strokes are heavy and its dot
# is large enough to read at a fifth of the frame's height.
_POSITION_MAP_STYLE = """
html,body{margin:0;padding:0}
body{width:100vw;height:100vh;background:#11131a;overflow:hidden;
box-sizing:border-box;border:1.2vw solid #3a4256;display:flex;
align-items:center;justify-content:center}
.map{width:84vw;height:84vw}
.route{fill:none;stroke:#6b7488;stroke-width:6;stroke-linejoin:round;
stroke-linecap:round}
.here{fill:none;stroke:#5aa9e6;stroke-width:8;stroke-linejoin:round;
stroke-linecap:round}
.mark{fill:#ffffff;stroke:none}
.on-map .route{stroke:#c9d0dc;stroke-width:11}
.on-map .here{stroke:#4fb3ff;stroke-width:16}
.on-map .mark{stroke:none}
"""
# The owner asked for the dot small and one colour: about four pixels of
# radius once the panel is a fifth of the frame high.
POSITION_MARK_RADIUS = 6


class ChapterCardError(ValueError):
    """Raised when a card cannot be laid out from the values given."""


def build_chapter_card_html(
    card: GapChapterCard,
    *,
    route_map_svg: str | None = None,
) -> str:
    """Lay one chapter card out as a self-contained HTML page.

    The page carries no external reference — no script, no stylesheet, no
    image, no font file — so rasterising it cannot reach the network, and the
    same input always draws the same card.
    """
    if not card.title or not card.body:
        raise ChapterCardError("a chapter card needs a title and a body")
    map_markup = f"\n{route_map_svg}" if route_map_svg else ""
    label_markup = f'<div class="label">{escape(card.label)}</div>\n' if card.label else ""
    body_markup = "<br>".join(escape(line) for line in card.body.split("\n"))
    return (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        f"<style>{_CARD_STYLE}</style>\n</head>\n<body>\n"
        f"{label_markup}"
        f'<div class="title">{escape(card.title)}</div>\n'
        f'<div class="body">{body_markup}</div>'
        f"{map_markup}\n</body>\n</html>\n"
    )


def build_position_map_html(route_map_svg: str) -> str:
    """The small map laid in a corner of every clip: where the ride is now.

    The whole page is the panel -- a dark square with a thin border -- so the
    film scales it down and lays it in the corner as it is. The SVG carries
    the route, the part ridden so far picked out, and a dot at the position.
    Like a card, the page references nothing outside itself.
    """
    if not route_map_svg:
        raise ChapterCardError("a position map needs the route drawn")
    return (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        f"<style>{_POSITION_MAP_STYLE}</style>\n</head>\n<body>\n"
        f"{route_map_svg}\n</body>\n</html>\n"
    )


def build_lower_third_html(
    card: GapChapterCard,
    *,
    route_map_svg: str | None = None,
) -> str:
    """Lay a chapter's title out as a lower third to go over its first window.

    The title and body are fitted to the overlay's budget (twelve and
    twenty-one characters; app.lower_third_text) by dropping the body's least
    essential parts, never by rewording. The route map, when given, sits at
    the right end of the strip. Like a card, the page references nothing
    outside itself.
    """
    if not card.title or not card.body:
        raise ChapterCardError("a chapter card needs a title and a body")
    # "出発" over "出発 · 112.3km" says the same thing twice; the body keeps
    # only what the title does not already say.
    parts = [part for part in card.body.split(BODY_SEPARATOR) if part.strip() != card.title]
    fitted = fit_lower_third_text(card.title, parts or [card.body])
    map_markup = f"\n{route_map_svg}" if route_map_svg else ""
    return (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        f"<style>{_LOWER_THIRD_STYLE}</style>\n</head>\n<body>\n"
        '<div class="band"><div class="strip">\n'
        f'<div class="text"><div class="title">{escape(fitted.title)}</div>\n'
        f'<div class="body">{escape(fitted.body)}</div></div>'
        f"{map_markup}\n</div></div>\n</body>\n</html>\n"
    )


SECTION_HEIGHT_SHARE = 1 / 9
_SECTION_STRIP_HEIGHT_VW = _BAND_HEIGHT_VW * SECTION_HEIGHT_SHARE
_SECTION_STYLE = f"""
html,body{{margin:0;padding:0}}
body{{width:100vw;height:100vh;background:#000;color:#fff;position:relative;
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN",
"Noto Sans CJK JP","Noto Sans JP","Helvetica Neue",Helvetica,Arial,sans-serif;
overflow:hidden}}
.band{{position:absolute;left:0;top:{_BAND_TOP_VW:.4f}vw;width:100vw;height:{_BAND_HEIGHT_VW:.4f}vw}}
.strip{{position:absolute;left:0;bottom:0;width:100vw;height:{_SECTION_STRIP_HEIGHT_VW:.4f}vw;
box-sizing:border-box;padding:0 4vw;display:flex;align-items:center;justify-content:flex-start}}
.line{{font-size:2.4vw;font-weight:600;letter-spacing:.05em;line-height:1.1;margin:0;
white-space:nowrap}}
"""


def build_section_html(text: str) -> str:
    """Lay a section's one line out as a slim strip to go over a window (点 8).

    Slimmer than the chapter's lower third and without a map: it says one
    thing -- through this town, off that highway -- and hands the frame
    back. The text is fitted to the lower third's body budget.
    """
    if not text.strip():
        raise ChapterCardError("a section needs its line")
    fitted = fit_title(text, max_chars=MAX_BODY_CHARS)
    return (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        f"<style>{_SECTION_STYLE}</style>\n</head>\n<body>\n"
        '<div class="band"><div class="strip">\n'
        f'<div class="line">{escape(fitted)}</div>\n</div></div>\n</body>\n</html>\n'
    )


def route_map_svg(
    points: tuple[RoutePoint, ...],
    *,
    highlight_from_index: int | None = None,
    highlight_to_index: int | None = None,
    mark_index: int | None = None,
    wide: bool = False,
    view_width: int = 320,
    view_height: int = 320,
    padding: int = 10,
    mark_radius: int = _MARK_RADIUS,
    background: MapBackground | None = None,
) -> str:
    """Draw the whole ride, with one stretch of it picked out -- or one point.

    With a `background` (E-10), the track is placed by the map's own
    projection over the map image embedded in the SVG, and the strokes are
    kept at their on-screen width whatever the page scales the map to.

    A stretch is the chapter's part of the route; a mark is a dot where the
    ride stood still, because a halt has no extent worth drawing. A wide map
    is for the cards that show the whole day (the headline and the close),
    where the route is the picture rather than a footnote.

    Longitude is scaled by the cosine of the route's mean latitude so the
    drawn shape matches the ride rather than stretching east-west, and the
    result is fitted into the view box with its aspect preserved. Only the
    shape survives that fitting: nothing in the markup says where on Earth
    the ride happened.

    The box is square by default because a ride can run any direction: a
    north-south route squeezed into a wide box draws too small to read.
    """
    if len(points) < 2:
        raise ChapterCardError("a route map needs at least two points")
    if view_width <= 2 * padding or view_height <= 2 * padding:
        raise ChapterCardError("a route map needs room inside its padding")

    sampled = _sampled(points)
    if background is not None:
        return _svg_over_map(
            sampled,
            points,
            background,
            highlight_from_index=highlight_from_index,
            highlight_to_index=highlight_to_index,
            mark_index=mark_index,
            wide=wide,
            mark_radius=mark_radius,
        )
    latitudes = [point.latitude for point in sampled]
    longitudes = [point.longitude for point in sampled]
    mean_latitude = sum(latitudes) / len(latitudes)
    scale_x = math.cos(math.radians(mean_latitude))
    xs = [longitude * scale_x for longitude in longitudes]
    ys = [-latitude for latitude in latitudes]  # north is up

    inner_width = view_width - 2 * padding
    inner_height = view_height - 2 * padding
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= 0 and span_y <= 0:
        raise ChapterCardError("a route map needs a route that moves")
    scale = min(
        inner_width / span_x if span_x > 0 else float("inf"),
        inner_height / span_y if span_y > 0 else float("inf"),
    )
    offset_x = padding + (inner_width - span_x * scale) / 2
    offset_y = padding + (inner_height - span_y * scale) / 2
    placed = [
        (
            offset_x + (x - min(xs)) * scale,
            offset_y + (y - min(ys)) * scale,
        )
        for x, y in zip(xs, ys, strict=True)
    ]

    whole = _points_attribute(placed)
    css_class = "map map-wide" if wide else "map"
    markup = [
        f'<svg class="{css_class}" viewBox="0 0 {view_width} {view_height}" '
        'preserveAspectRatio="xMidYMid meet" '
        'xmlns="http://www.w3.org/2000/svg">',
        f'<polyline class="route" points="{whole}"/>',
    ]
    highlighted = _highlighted(placed, points, highlight_from_index, highlight_to_index)
    if highlighted:
        markup.append(f'<polyline class="here" points="{_points_attribute(highlighted)}"/>')
    if mark_index is not None:
        if not 0 <= mark_index < len(points):
            raise ChapterCardError("a mark must lie on the route")
        x, y = placed[_placed_index(placed, points, mark_index)]
        markup.append(f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="{mark_radius}"/>')
    markup.append("</svg>")
    return "\n".join(markup)


def _placed_index(
    placed: list[tuple[float, float]], points: tuple[RoutePoint, ...], index: int
) -> int:
    """`placed` may have been thinned, so map a route index onto it."""
    ratio = (len(placed) - 1) / (len(points) - 1) if len(points) > 1 else 0.0
    return min(len(placed) - 1, round(index * ratio))


def _svg_over_map(
    sampled: tuple[RoutePoint, ...],
    points: tuple[RoutePoint, ...],
    background: MapBackground,
    *,
    highlight_from_index: int | None,
    highlight_to_index: int | None,
    mark_index: int | None,
    wide: bool,
    mark_radius: int,
) -> str:
    """The route drawn on the fetched map, in the map image's own pixels."""
    size = background.frame.pixels
    placed = [background.frame.project(p.latitude, p.longitude) for p in sampled]
    # Strokes were sized for a 320-unit box; keep them that size on screen.
    keep = ' vector-effect="non-scaling-stroke"'
    css_class = "map map-wide on-map" if wide else "map on-map"
    markup = [
        f'<svg class="{css_class}" viewBox="0 0 {size} {size}" '
        'preserveAspectRatio="xMidYMid meet" '
        'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">',
        f'<image href="{background.data_uri}" xlink:href="{background.data_uri}" '
        f'x="0" y="0" width="{size}" height="{size}"/>',
        f'<polyline class="route" points="{_points_attribute(placed)}"{keep}/>',
    ]
    highlighted = _highlighted(placed, points, highlight_from_index, highlight_to_index)
    if highlighted:
        markup.append(f'<polyline class="here" points="{_points_attribute(highlighted)}"{keep}/>')
    if mark_index is not None:
        if not 0 <= mark_index < len(points):
            raise ChapterCardError("a mark must lie on the route")
        x, y = placed[_placed_index(placed, points, mark_index)]
        radius = mark_radius * size / 320
        markup.append(f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}"{keep}/>')
    markup.append("</svg>")
    return "\n".join(markup)


def _sampled(points: tuple[RoutePoint, ...]) -> tuple[RoutePoint, ...]:
    """Thin a long track deterministically, always keeping both ends."""
    if len(points) <= _MAX_MAP_POINTS:
        return points
    step = math.ceil(len(points) / _MAX_MAP_POINTS)
    kept = list(points[::step])
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return tuple(kept)


def _highlighted(
    placed: list[tuple[float, float]],
    points: tuple[RoutePoint, ...],
    from_index: int | None,
    to_index: int | None,
) -> list[tuple[float, float]]:
    if from_index is None or to_index is None:
        return []
    if not 0 <= from_index <= to_index < len(points):
        raise ChapterCardError("a highlighted stretch must lie inside the route")
    start = _placed_index(placed, points, from_index)
    end = _placed_index(placed, points, to_index)
    if end - start < 1:
        end = min(len(placed) - 1, start + 1)
    return placed[start : end + 1]


def _points_attribute(placed: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in placed)
