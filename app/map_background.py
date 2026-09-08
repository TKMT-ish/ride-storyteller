"""A real map behind the route figures, from Google's Static Maps (E-10).

The owner asked, after the second viewing, why the route figures sit on
black when Google's services are already in use. This module fetches one
square, dark-styled map image that covers the whole ride, keeps it in the
package, and gives the drawing code the projection that places any point
of the track on that image -- so the route, the stretch, the halt and the
current position are still drawn here, on this machine, in the same SVG as
before, only now over a map.

What leaves the machine is the centre of the ride's bounding box and a
zoom level, nothing else: not the track, not a file name, not a time. The
key travels in the request and is never written or logged. The fetched
image is cached under the package directory, which is never committed, and
it is refetched only when the ride's bounds or the style change.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import load_local_environment
from app.contracts import RoutePoint

STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
# The largest square the API serves; at scale 2 it is 1280 px across, which
# is enough for the headline card's map (30% of a 1920 frame) and far more
# than the corner map needs.
MAP_SIZE_PX = 640
MAP_SCALE = 2
# The route keeps this much of the image's width free around it.
ROUTE_FIT_SHARE = 0.84
MAX_ZOOM = 18

# Dark, quiet: the picture is the ride, the map is where it happened. Roads
# and water are shapes; towns keep their names; points of interest, transit
# and road names are noise at this size.
DARK_STYLE: tuple[str, ...] = (
    "element:geometry|color:0x1c2130",
    "element:labels.text.fill|color:0x9aa3b5",
    "element:labels.text.stroke|color:0x11131a",
    "feature:water|element:geometry|color:0x0e1826",
    "feature:road|element:geometry|color:0x3a4256",
    "feature:road|element:labels|visibility:off",
    "feature:poi|visibility:off",
    "feature:transit|visibility:off",
    "feature:administrative|element:geometry|visibility:off",
)
# The same, with every label off: for an owner who wants no place names
# anywhere in the picture.
UNLABELLED_STYLE: tuple[str, ...] = (*DARK_STYLE, "element:labels|visibility:off")

Fetcher = Callable[[str], bytes]

# How the film's maps look: "labels" keeps town names, "plain" has no text at
# all, "none" draws the route on black as before. Read from the environment
# so the owner can compare without a code change.
MAP_STYLE_ENV = "RIDE_MAP_STYLE"
MAP_STYLES: dict[str, tuple[str, ...]] = {"labels": DARK_STYLE, "plain": UNLABELLED_STYLE}
# The owner compared both on the second real day (2026-09-05) and chose the
# towns named; the corner map takes the map without text whatever this is.
DEFAULT_MAP_STYLE = "labels"


class MapBackgroundError(RuntimeError):
    """Raised when the map cannot be fetched or placed."""


@dataclass(frozen=True)
class MapFrame:
    """One square map image and the projection that places the track on it."""

    center_latitude: float
    center_longitude: float
    zoom: int
    size_px: int = MAP_SIZE_PX
    scale: int = MAP_SCALE

    def __post_init__(self) -> None:
        if (
            not -85.0 <= self.center_latitude <= 85.0
            or not -180.0 <= self.center_longitude <= 180.0
        ):
            raise MapBackgroundError("the map centre must be a place on Earth")
        if not 0 <= self.zoom <= MAX_ZOOM:
            raise MapBackgroundError("the zoom must be between 0 and 18")
        if self.size_px <= 0 or self.scale not in (1, 2):
            raise MapBackgroundError("the map needs a positive size and a scale of 1 or 2")

    @property
    def pixels(self) -> int:
        """The fetched image's width and height."""
        return self.size_px * self.scale

    def project(self, latitude: float, longitude: float) -> tuple[float, float]:
        """Where a point of the track falls on the image, in image pixels."""
        x = _world_x(longitude, self.zoom) - _world_x(self.center_longitude, self.zoom)
        y = _world_y(latitude, self.zoom) - _world_y(self.center_latitude, self.zoom)
        half = self.pixels / 2
        return half + x * self.scale, half + y * self.scale

    def key(self, style: Sequence[str]) -> str:
        """Names the cached image: same frame and style, same file."""
        material = (
            f"{self.center_latitude:.5f},{self.center_longitude:.5f},{self.zoom},"
            f"{self.size_px},{self.scale}," + "|".join(style)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MapBackground:
    """A fetched map ready to draw on: its frame, and the image as a data URI.

    The URI goes straight into the SVG, so the drawn page still references
    nothing outside itself.
    """

    frame: MapFrame
    data_uri: str

    def __post_init__(self) -> None:
        if not self.data_uri.startswith("data:image/png;base64,"):
            raise MapBackgroundError("a map background is a PNG data URI")

    @classmethod
    def from_file(cls, frame: MapFrame, path: Path) -> MapBackground:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG"):
            raise MapBackgroundError("the cached map is not a PNG")
        return cls(frame, "data:image/png;base64," + base64.b64encode(data).decode("ascii"))


def style_named(name: str) -> tuple[str, ...]:
    """The style rules for a named look; "none" has no rules because it fetches nothing."""
    if name == "none":
        return ()
    try:
        return MAP_STYLES[name]
    except KeyError as error:
        raise MapBackgroundError(f"unknown map style: {name!r}") from error


def chosen_style_name() -> str:
    """The look the environment asks for, defaulting to towns named."""
    return (
        os.environ.get(MAP_STYLE_ENV, load_local_environment().get(MAP_STYLE_ENV, ""))
        .strip()
        .lower()
        or DEFAULT_MAP_STYLE
    )


def background_or_none(
    package_directory: Path,
    points: Sequence[RoutePoint],
    *,
    style_name: str | None = None,
    key: str | None = None,
    fetch: Fetcher | None = None,
) -> MapBackground | None:
    """The map to draw on, or None: no key, no service, or a look of "none".

    A film without a map background is still a film; the caller draws the
    route on black as before and says so in its result.
    """
    name = style_name or chosen_style_name()
    if name == "none":
        return None
    try:
        frame, path = map_background(
            package_directory, points, style=style_named(name), key=key, fetch=fetch or _fetch
        )
        return MapBackground.from_file(frame, path)
    except MapBackgroundError:
        return None


def frame_for(points: Sequence[RoutePoint], *, size_px: int = MAP_SIZE_PX) -> MapFrame:
    """The square that fits the whole ride, with room around it, as far in as it goes."""
    if len(points) < 2:
        raise MapBackgroundError("a map frame needs at least two points")
    latitudes = [p.latitude for p in points]
    longitudes = [p.longitude for p in points]
    center_lat = (max(latitudes) + min(latitudes)) / 2
    center_lon = (max(longitudes) + min(longitudes)) / 2
    zoom = 0
    for candidate in range(1, MAX_ZOOM + 1):
        width = _world_x(max(longitudes), candidate) - _world_x(min(longitudes), candidate)
        height = _world_y(min(latitudes), candidate) - _world_y(max(latitudes), candidate)
        if max(width, height) <= size_px * ROUTE_FIT_SHARE:
            zoom = candidate
        else:
            break
    return MapFrame(center_lat, center_lon, zoom, size_px=size_px)


def static_map_url(frame: MapFrame, *, style: Sequence[str], key: str, language: str = "ja") -> str:
    """The request: centre, zoom, size, style and key. The track is not in it."""
    if not key:
        raise MapBackgroundError("a Google Maps key is needed to fetch a map")
    params = [
        ("center", f"{frame.center_latitude:.5f},{frame.center_longitude:.5f}"),
        ("zoom", str(frame.zoom)),
        ("size", f"{frame.size_px}x{frame.size_px}"),
        ("scale", str(frame.scale)),
        ("maptype", "roadmap"),
        ("format", "png"),
        ("language", language),
        *(("style", rule) for rule in style),
        ("key", key),
    ]
    return STATIC_MAPS_URL + "?" + urllib.parse.urlencode(params)


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - fixed https host
            if "image" not in (response.headers.get("Content-Type") or ""):
                raise MapBackgroundError("the map service did not return an image")
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise MapBackgroundError(
                "the map service refused the request: the Static Maps API may not be "
                "enabled for this key's project"
            ) from error
        raise MapBackgroundError(f"the map service answered {error.code}") from error
    except urllib.error.URLError as error:
        raise MapBackgroundError("the map service could not be reached") from error


def maps_key() -> str:
    """The configured Google Maps key, or an empty string. Never logged."""
    return os.environ.get(
        "GOOGLE_MAPS_API_KEY", load_local_environment().get("GOOGLE_MAPS_API_KEY", "")
    ).strip()


def map_background(
    package_directory: Path,
    points: Sequence[RoutePoint],
    *,
    style: Sequence[str] = DARK_STYLE,
    key: str | None = None,
    fetch: Fetcher = _fetch,
) -> tuple[MapFrame, Path]:
    """The ride's map image, fetched once and kept beside the package's other work.

    Returns the frame (for projecting the track) and the PNG's path. Raises
    when no key is configured or the fetch fails; callers decide whether a
    film without a map background is still a film (it is).
    """
    frame = frame_for(points)
    cache = package_directory / "map-background"
    if cache.is_symlink():
        raise MapBackgroundError("the map cache path is unsafe")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"map-{frame.key(style)}.png"
    if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
        return frame, path
    secret = maps_key() if key is None else key
    data = fetch(static_map_url(frame, style=style, key=secret))
    if not data.startswith(b"\x89PNG"):
        raise MapBackgroundError("the map service did not return a PNG")
    temporary = path.with_suffix(".part")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return frame, path


def _world_x(longitude: float, zoom: int) -> float:
    return (longitude + 180.0) / 360.0 * 256.0 * 2**zoom


def _world_y(latitude: float, zoom: int) -> float:
    sine = math.sin(math.radians(max(-85.05, min(85.05, latitude))))
    return (0.5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi)) * 256.0 * 2**zoom
