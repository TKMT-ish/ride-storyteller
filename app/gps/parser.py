"""Dependency-free GPX parser for the Day 2 route contract."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from app.contracts import RoutePoint, RouteSummary

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class ParsedRoute:
    summary: RouteSummary
    points: tuple[RoutePoint, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary.to_dict(),
            "points": [point.to_dict() for point in self.points],
        }


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("GPX timestamps must include a timezone")
    return timestamp.astimezone(UTC)


def _distance_m(a: RoutePoint, latitude: float, longitude: float) -> float:
    lat_1, lat_2 = math.radians(a.latitude), math.radians(latitude)
    d_lat = lat_2 - lat_1
    d_lon = math.radians(longitude - a.longitude)
    haversine = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(haversine))


def _child_text(point: ElementTree.Element, name: str) -> str | None:
    child = point.find(f"{{*}}{name}")
    return child.text if child is not None else None


def parse_gpx(path: Path) -> ParsedRoute:
    """Parse a private GPX file and derive distance, speed, and route summary."""
    return _parse_root(ElementTree.parse(path).getroot())


def parse_gpx_bytes(contents: bytes) -> ParsedRoute:
    """Parse an in-memory GPX upload without writing it to disk."""
    return _parse_root(ElementTree.fromstring(contents))


def _parse_root(root: ElementTree.Element) -> ParsedRoute:
    raw_points = root.findall(".//{*}trkpt")
    if not raw_points:
        raise ValueError("GPX contains no track points")

    points: list[RoutePoint] = []
    elevation_gain_m = 0.0
    elevation_loss_m = 0.0
    for raw in raw_points:
        time_text = _child_text(raw, "time")
        if time_text is None:
            raise ValueError("every GPX track point must include time")
        latitude = float(raw.attrib["lat"])
        longitude = float(raw.attrib["lon"])
        elevation_text = _child_text(raw, "ele")
        elevation_m = float(elevation_text) if elevation_text is not None else None
        timestamp = _parse_timestamp(time_text)

        if not points:
            point = RoutePoint(timestamp, latitude, longitude, elevation_m, 0.0, None)
        else:
            previous = points[-1]
            segment_m = _distance_m(previous, latitude, longitude)
            elapsed_s = (timestamp - previous.timestamp).total_seconds()
            if elapsed_s <= 0:
                raise ValueError("GPX track point times must be strictly increasing")
            speed_mps = segment_m / elapsed_s
            point = RoutePoint(
                timestamp, latitude, longitude, elevation_m,
                previous.distance_from_start_m + segment_m, speed_mps,
            )
            if elevation_m is not None and previous.elevation_m is not None:
                change = elevation_m - previous.elevation_m
                elevation_gain_m += max(change, 0)
                elevation_loss_m += max(-change, 0)
        points.append(point)

    summary = RouteSummary(
        point_count=len(points),
        start_time=points[0].timestamp,
        end_time=points[-1].timestamp,
        total_distance_m=points[-1].distance_from_start_m,
        duration_s=(points[-1].timestamp - points[0].timestamp).total_seconds(),
        elevation_gain_m=elevation_gain_m,
        elevation_loss_m=elevation_loss_m,
    )
    return ParsedRoute(summary, tuple(points))


def main() -> None:
    command = argparse.ArgumentParser(description="Normalize a GPX track into route.json")
    command.add_argument("input", type=Path, help="private GPX input file")
    command.add_argument("--output", type=Path, required=True, help="route.json output path")
    args = command.parse_args()
    route_json = json.dumps(parse_gpx(args.input).to_dict(), ensure_ascii=False, indent=2)
    args.output.write_text(route_json)


if __name__ == "__main__":
    main()
