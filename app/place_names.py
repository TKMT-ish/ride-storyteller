"""Where the ride went from and to, in words: place names for the legs.

The owner's second rule (2026-09-06): a chapter's title says where the
leg went from and where it went to. The track has no names in it, so the
two ends of every leg -- and the day's own ends -- are asked of Google's
Geocoding API, one request per point, with the answer kept in the package
so a re-cut asks nothing again.

What leaves the machine is a single coordinate per request, rounded to
four decimals (about ten metres), and the language wanted. Never the
track, never a time, never a file name. `docs/data-flows-ja.md` lists it.

The name used is the most local one the answer carries -- a town, a
village, a suburb of a city -- and failing those the district; a road's
name is kept beside it for the turning points (point 4 of the same note).
Two finer names ride along (the owner, 2026-09-07: a city's name says
nothing about a lookout or a museum inside it): the suburb inside a city,
and the spot -- a named place the service knows at that point, a museum, a
park, a terminal -- when its answer carries one.
A point the service cannot name, a key that is missing, a service that
refuses: each leaves the name empty, and the card falls back to the
title the track alone allows. No film waits on a name.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import load_local_environment
from app.contracts import RoutePoint

GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACE_NAMES_FILE_NAME = "place-names.json"
PLACE_NAMES_SCHEMA_VERSION = "place-names-v1"
# Four decimals of a degree: ten metres or so, enough to name a town and
# not enough to say which driveway.
COORDINATE_DECIMALS = 4

# Address component types, most local first, that name a place a rider
# would say they were at.
_PLACE_TYPES: tuple[str, ...] = (
    "locality",
    "postal_town",
    "sublocality_level_1",
    "sublocality",
    "neighborhood",
    "administrative_area_level_3",
    "administrative_area_level_2",
    "natural_feature",
)
_ROAD_TYPES: tuple[str, ...] = ("route",)
# A suburb or a neighbourhood inside a city, most local first.
_SUBURB_TYPES: tuple[str, ...] = ("sublocality_level_1", "sublocality", "neighborhood")
# A named place at the point itself, when the answer carries one.
_SPOT_TYPES: tuple[str, ...] = (
    "point_of_interest",
    "establishment",
    "natural_feature",
    "park",
    "transit_station",
)

Fetcher = Callable[[str], bytes]


class PlaceNamesError(RuntimeError):
    """Raised when a name cannot be asked for or kept."""


@dataclass(frozen=True)
class PlaceName:
    """What a point is called: the place, the road it is on, the suburb, the spot."""

    place: str | None
    road: str | None
    suburb: str | None = None
    spot: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"place": self.place, "road": self.road, "suburb": self.suburb, "spot": self.spot}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PlaceName:
        def text(key: str) -> str | None:
            value = payload.get(key)
            return str(value) if isinstance(value, str) and value else None

        return cls(place=text("place"), road=text("road"), suburb=text("suburb"), spot=text("spot"))

    @property
    def finer(self) -> str | None:
        """The most specific name: the spot, else the suburb, else the place."""
        return self.spot or self.suburb or self.place


NOTHING = PlaceName(place=None, road=None)


def rounded(latitude: float, longitude: float) -> tuple[float, float]:
    return round(latitude, COORDINATE_DECIMALS), round(longitude, COORDINATE_DECIMALS)


def geocoding_url(latitude: float, longitude: float, *, key: str, language: str) -> str:
    """The request: one rounded coordinate, the language, the key. Nothing else."""
    lat, lon = rounded(latitude, longitude)
    params = {"latlng": f"{lat:.4f},{lon:.4f}", "language": language, "key": key}
    return GEOCODING_URL + "?" + urllib.parse.urlencode(params)


def parse_geocoding(payload: Mapping[str, object]) -> PlaceName:
    """The most local place and the road, from the service's answer."""
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        return NOTHING
    if status != "OK":
        raise PlaceNamesError(f"the place service answered {status}")
    results = payload.get("results")
    if not isinstance(results, list):
        raise PlaceNamesError("the place service answered without results")
    found: dict[str, str] = {}
    spot: str | None = None
    for result in results:
        if not isinstance(result, Mapping):
            continue
        components = result.get("address_components")
        if not isinstance(components, list):
            continue
        own_types = result.get("types")
        is_spot = isinstance(own_types, list) and any(t in own_types for t in _SPOT_TYPES)
        for component in components:
            if not isinstance(component, Mapping):
                continue
            name = component.get("long_name")
            types = component.get("types")
            if not isinstance(name, str) or not name or not isinstance(types, list):
                continue
            if spot is None and is_spot and any(t in types for t in _SPOT_TYPES):
                spot = name
            for kind in (*_PLACE_TYPES, *_ROAD_TYPES, *_SUBURB_TYPES):
                if kind in types:
                    found.setdefault(kind, name)
    place = next((found[kind] for kind in _PLACE_TYPES if kind in found), None)
    road = next((found[kind] for kind in _ROAD_TYPES if kind in found), None)
    suburb = next((found[kind] for kind in _SUBURB_TYPES if kind in found), None)
    if road is not None and road.lower().startswith("unnamed"):
        road = None
    if suburb == place:
        suburb = None
    return PlaceName(place=place, road=road, suburb=suburb, spot=spot)


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - fixed https host
            return response.read()
    except urllib.error.HTTPError as error:
        raise PlaceNamesError(f"the place service answered {error.code}") from error
    except urllib.error.URLError as error:
        raise PlaceNamesError("the place service could not be reached") from error


def maps_key() -> str:
    """The configured Google Maps key, or an empty string. Never logged."""
    return os.environ.get(
        "GOOGLE_MAPS_API_KEY", load_local_environment().get("GOOGLE_MAPS_API_KEY", "")
    ).strip()


class PlaceNames:
    """The package's names, asked once each and kept beside its other work."""

    def __init__(
        self,
        package_directory: Path,
        *,
        language: str = "ja",
        key: str | None = None,
        fetch: Fetcher = _fetch,
    ) -> None:
        self._path = package_directory / PLACE_NAMES_FILE_NAME
        if self._path.is_symlink():
            raise PlaceNamesError("the place-names path is unsafe")
        self._language = language
        self._key = key
        self._fetch = fetch
        self._known: dict[str, PlaceName] = {}
        if self._path.is_file():
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise PlaceNamesError("the place-names file is unreadable") from error
            if payload.get("schema_version") != PLACE_NAMES_SCHEMA_VERSION:
                raise PlaceNamesError("unsupported place-names schema")
            names = payload.get("names")
            if isinstance(names, dict):
                for key_text, item in names.items():
                    # An answer kept before the suburb and the spot were read
                    # is asked again; the service is cheap and the film is not.
                    if isinstance(item, Mapping) and "suburb" in item:
                        self._known[str(key_text)] = PlaceName.from_dict(item)
        self.asked = 0

    def _key_for(self, latitude: float, longitude: float) -> str:
        lat, lon = rounded(latitude, longitude)
        return f"{lat:.4f},{lon:.4f}@{self._language}"

    def name_at(self, latitude: float, longitude: float) -> PlaceName:
        """The name of this point, asked of the service once and remembered."""
        cache_key = self._key_for(latitude, longitude)
        known = self._known.get(cache_key)
        if known is not None:
            return known
        secret = maps_key() if self._key is None else self._key
        if not secret:
            raise PlaceNamesError("no Google Maps key is configured")
        raw = self._fetch(geocoding_url(latitude, longitude, key=secret, language=self._language))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PlaceNamesError("the place service did not answer in JSON") from error
        if not isinstance(payload, dict):
            raise PlaceNamesError("the place service did not answer in JSON")
        name = parse_geocoding(payload)
        self.asked += 1
        self._known[cache_key] = name
        self._write()
        return name

    def _write(self) -> None:
        payload = {
            "schema_version": PLACE_NAMES_SCHEMA_VERSION,
            "language": self._language,
            "names": {key: name.to_dict() for key, name in sorted(self._known.items())},
        }
        temporary = self._path.with_suffix(".part")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)


def point_at(points: Sequence[RoutePoint], when) -> RoutePoint:
    """The track point nearest this time."""
    if not points:
        raise PlaceNamesError("a track needs at least one point")
    return min(points, key=lambda p: abs((p.timestamp - when).total_seconds()))


def leg_names(
    names: PlaceNames, points: Sequence[RoutePoint], spans: Sequence[tuple]
) -> list[tuple[PlaceName, PlaceName]]:
    """From and to, for each (start_time, end_time) span, asking only once per point."""
    out: list[tuple[PlaceName, PlaceName]] = []
    for start, end in spans:
        first, last = point_at(points, start), point_at(points, end)
        out.append(
            (
                names.name_at(first.latitude, first.longitude),
                names.name_at(last.latitude, last.longitude),
            )
        )
    return out
