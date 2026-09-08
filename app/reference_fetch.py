"""Fetch the reference files the film reads, from OpenStreetMap through Overpass.

The film names what the track alone cannot: a town it came through, a
pass it crossed, a ferry it rode, a road with a name worth saying (the
owner, 2026-09-07: the famous road on day 2, the ferry on day 3, the
town on day 10). Each is a reference file under `private-media/reference/`,
never in git, fetched once for a region and read offline after that.

One request per kind, to a public Overpass mirror, asking for a region by
its ISO code. Nothing about any ride leaves the machine: the request names
a country and a kind of thing, and for named roads the names asked for,
which come from a private list beside the reference. The answer is
written in the shapes the readers expect:

- `touring-routes-v1` (app.scenic_routes) for ferries and named roads:
  `routes[].name`, `routes[].lines[][lat, lon]`.
- `places-v1` (app.places) for towns: `places[].name/kind/population/
  latitude/longitude`.
- `landmarks-v1` (app.places) for passes: `landmarks[].name/kind/
  latitude/longitude/elevation_m`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

PLACES_SCHEMA_VERSION = "places-v1"
LANDMARKS_SCHEMA_VERSION = "landmarks-v1"
TOURING_ROUTES_SCHEMA_VERSION = "touring-routes-v1"
SOURCE = "OpenStreetMap via Overpass API (ODbL)"
# Public mirrors, tried in order; the first that answers with JSON wins.
OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
KINDS: tuple[str, ...] = ("places", "passes", "ferries", "named-roads")
# Towns of these OSM kinds are worth a line; hamlets and localities are not.
PLACE_KINDS: tuple[str, ...] = ("city", "town", "village")

Fetcher = Callable[[str, bytes], bytes]


class ReferenceFetchError(RuntimeError):
    """Raised when the request cannot be built, sent, or its answer trusted."""


def overpass_query(kind: str, region: str, *, names: Sequence[str] = ()) -> str:
    """The Overpass QL for one kind of reference in one region."""
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise ReferenceFetchError("the region must be a two-letter ISO code")
    head = f'[out:json][timeout:180];\narea["ISO3166-1"="{region}"]->.a;\n'
    if kind == "places":
        kinds = "|".join(PLACE_KINDS)
        return head + f'node["place"~"^({kinds})$"]["name"](area.a);\nout;'
    if kind == "passes":
        return head + 'node["mountain_pass"="yes"]["name"](area.a);\nout;'
    if kind == "ferries":
        return head + 'way["route"="ferry"]["name"](area.a);\nout geom;'
    if kind == "named-roads":
        wanted = [n.strip() for n in names if n.strip()]
        if not wanted:
            raise ReferenceFetchError("named roads need at least one name to ask for")
        pattern = "|".join(re.escape(n) for n in wanted)
        return head + f'way["highway"]["name"~"^({pattern})$"](area.a);\nout geom;'
    raise ReferenceFetchError(f"unknown reference kind: {kind}")


def _elements(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ReferenceFetchError("the Overpass answer carries no elements")
    return [e for e in elements if isinstance(e, Mapping)]


def _tags(element: Mapping[str, object]) -> Mapping[str, object]:
    tags = element.get("tags")
    return tags if isinstance(tags, Mapping) else {}


def _number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        match = re.match(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            return float(match.group())
    return None


def parse_places(payload: Mapping[str, object], region: str) -> dict[str, object]:
    """Towns as `places-v1`, sorted by name."""
    places: list[dict[str, object]] = []
    for element in _elements(payload):
        tags = _tags(element)
        name, kind = tags.get("name"), tags.get("place")
        lat, lon = _number(element.get("lat")), _number(element.get("lon"))
        if not isinstance(name, str) or kind not in PLACE_KINDS or lat is None or lon is None:
            continue
        population = _number(tags.get("population"))
        places.append(
            {
                "name": name.strip(),
                "kind": kind,
                "population": int(population) if population is not None else None,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
            }
        )
    places.sort(key=lambda p: (str(p["name"]), float(p["latitude"])))
    return {
        "schema": PLACES_SCHEMA_VERSION,
        "region": region,
        "source": SOURCE,
        "fetched": date.today().isoformat(),
        "places": places,
    }


def parse_passes(payload: Mapping[str, object], region: str) -> dict[str, object]:
    """Road passes as `landmarks-v1`, sorted by name."""
    landmarks: list[dict[str, object]] = []
    for element in _elements(payload):
        tags = _tags(element)
        name = tags.get("name")
        lat, lon = _number(element.get("lat")), _number(element.get("lon"))
        if not isinstance(name, str) or lat is None or lon is None:
            continue
        landmarks.append(
            {
                "name": name.strip(),
                "kind": "pass",
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "elevation_m": _number(tags.get("ele")),
            }
        )
    landmarks.sort(key=lambda p: (str(p["name"]), float(p["latitude"])))
    return {
        "schema": LANDMARKS_SCHEMA_VERSION,
        "region": region,
        "source": SOURCE,
        "fetched": date.today().isoformat(),
        "landmarks": landmarks,
    }


def parse_ways(payload: Mapping[str, object], region: str, kind: str) -> dict[str, object]:
    """Named ways as `touring-routes-v1`, one route per name with all its lines."""
    lines: dict[str, list[list[list[float]]]] = {}
    for element in _elements(payload):
        if element.get("type") != "way":
            continue
        name = _tags(element).get("name")
        geometry = element.get("geometry")
        if not isinstance(name, str) or not isinstance(geometry, list):
            continue
        line: list[list[float]] = []
        for node in geometry:
            if not isinstance(node, Mapping):
                continue
            lat, lon = _number(node.get("lat")), _number(node.get("lon"))
            if lat is not None and lon is not None:
                line.append([round(lat, 6), round(lon, 6)])
        if len(line) >= 2:
            lines.setdefault(name.strip(), []).append(line)
    routes = [{"name": name, "lines": lines[name]} for name in sorted(lines)]
    return {
        "schema": TOURING_ROUTES_SCHEMA_VERSION,
        "region": region,
        "kind": kind,
        "source": SOURCE,
        "fetched": date.today().isoformat(),
        "routes": routes,
    }


def parse(kind: str, payload: Mapping[str, object], region: str) -> dict[str, object]:
    if kind == "places":
        return parse_places(payload, region)
    if kind == "passes":
        return parse_passes(payload, region)
    if kind in ("ferries", "named-roads"):
        return parse_ways(payload, region, kind)
    raise ReferenceFetchError(f"unknown reference kind: {kind}")


USER_AGENT = "ride-storyteller-reference-fetch/1 (offline film references)"


def _post(url: str, body: bytes) -> bytes:
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "text/plain; charset=utf-8")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=200) as response:  # noqa: S310 - fixed hosts
            return response.read()
    except urllib.error.HTTPError as error:
        raise ReferenceFetchError(f"the mirror answered {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ReferenceFetchError("the mirror could not be reached") from error


def fetch(
    query: str,
    *,
    endpoints: Sequence[str] = OVERPASS_ENDPOINTS,
    post: Fetcher = _post,
) -> dict[str, object]:
    """Ask the mirrors in turn; the first JSON answer with elements is returned."""
    failures: list[str] = []
    body = query.encode("utf-8")
    for endpoint in endpoints:
        try:
            raw = post(endpoint, body)
            payload = json.loads(raw.decode("utf-8"))
        except ReferenceFetchError as error:
            failures.append(f"{endpoint}: {error}")
            continue
        except (UnicodeDecodeError, json.JSONDecodeError):
            failures.append(f"{endpoint}: not JSON")
            continue
        if isinstance(payload, dict) and isinstance(payload.get("elements"), list):
            return payload
        failures.append(f"{endpoint}: no elements")
    raise ReferenceFetchError("no mirror answered: " + "; ".join(failures))


def write_reference(path: Path, payload: Mapping[str, object]) -> None:
    if path.is_symlink():
        raise ReferenceFetchError("the reference path is unsafe")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def read_names(path: Path) -> tuple[str, ...]:
    """The wanted road names, one per line; blank lines and `#` comments skipped."""
    if path.is_symlink() or not path.is_file():
        raise ReferenceFetchError("the names file is unavailable")
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            names.append(text)
    return tuple(names)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch a reference file from OpenStreetMap.")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("--region", required=True, help="two-letter ISO country code")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--names", type=Path, help="named-roads: file of road names to ask for")
    args = parser.parse_args(argv)
    try:
        names = read_names(args.names) if args.names else ()
        query = overpass_query(args.kind, args.region, names=names)
        payload = parse(args.kind, fetch(query), args.region)
        write_reference(args.out, payload)
    except ReferenceFetchError as error:
        print(f"reference fetch failed: {error}", file=sys.stderr)
        return 1
    count = len(payload.get("routes", payload.get("places", payload.get("landmarks", []))))
    print(f"{args.kind}: {count} entries -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
