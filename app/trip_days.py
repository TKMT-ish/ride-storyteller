"""Which day of the trip a package is, and what the local clock says.

The owner's day-1 notes (2026-09-07, points 9 and 10): the lower thirds
carry the local time, and on a trip of several days every full-screen
card says which day it is. Neither is written anywhere, so both are read
off what the packages already hold.

The day: the packages beside this one (the same `work/` directory) each
have a track with a date; when this package's date belongs to a run of
consecutive dates with at least one other, the trip is multi-day and the
day is the date's place in that run. A lone date is a day trip: no label.

The clock: the camera was set to local time and the package knows how
far its clock sat from GPS (UTC), so the local offset is the negative of
that, rounded to a quarter hour -- when it looks like a time zone at all.
`RIDE_LOCAL_UTC_OFFSET` ("+13:00") overrides it.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.video import load_video_catalog

LOCAL_OFFSET_ENV = "RIDE_LOCAL_UTC_OFFSET"
_TIME_TAG = re.compile(rb"<time>([^<]+)</time>")
_OFFSET = re.compile(r"^([+-])(\d{1,2}):?(\d{2})$")
# A camera clock this far from UTC is a time zone; nearer is drift, farther is nonsense.
_ZONE_MIN_S = 30 * 60.0
_ZONE_MAX_S = 14 * 3600.0


def local_offset_s(package_directory: Path) -> float | None:
    """Seconds to add to UTC for the local clock, or None when unknown."""
    named = os.environ.get(LOCAL_OFFSET_ENV, "").strip()
    if named:
        match = _OFFSET.match(named)
        if not match:
            raise ValueError("RIDE_LOCAL_UTC_OFFSET must look like +13:00")
        sign = 1 if match.group(1) == "+" else -1
        return sign * (int(match.group(2)) * 3600 + int(match.group(3)) * 60)
    try:
        catalog = load_video_catalog(package_directory / "local-video-catalog.json")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    camera = -catalog.video_to_gps_offset_s
    if not _ZONE_MIN_S <= abs(camera) <= _ZONE_MAX_S:
        return None
    return round(camera / 900.0) * 900.0


def _first_time(gpx_path: Path) -> datetime | None:
    """The first <time> in a GPX file, read from its head without parsing it all."""
    try:
        with gpx_path.open("rb") as handle:
            head = handle.read(65536)
    except OSError:
        return None
    match = _TIME_TAG.search(head)
    if not match:
        return None
    text = match.group(1).decode("ascii", "ignore").strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def package_date(package_directory: Path, local_offset: float | None) -> date | None:
    """The local date the package's track begins on."""
    try:
        payload = json.loads(
            (package_directory / "local-pipeline-inputs.json").read_text(encoding="utf-8")
        )
        gpx_path = Path(str(payload["gpx_path"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    first = _first_time(gpx_path)
    if first is None:
        return None
    return (first + timedelta(seconds=local_offset or 0.0)).date()


def trip_day(package_directory: Path, *, local_offset: float | None = None) -> int | None:
    """This package's day number in a run of consecutive days, or None for a day trip."""
    mine = package_date(package_directory, local_offset)
    if mine is None:
        return None
    parent = package_directory.resolve().parent
    dates: set[date] = {mine}
    for sibling in parent.iterdir():
        if not sibling.is_dir() or sibling.is_symlink():
            continue
        if not (sibling / "local-pipeline-inputs.json").is_file():
            continue
        found = package_date(sibling, local_offset)
        if found is not None:
            dates.add(found)
    run = [mine]
    earlier = mine
    while earlier - timedelta(days=1) in dates:
        earlier -= timedelta(days=1)
        run.insert(0, earlier)
    later = mine
    while later + timedelta(days=1) in dates:
        later += timedelta(days=1)
        run.append(later)
    if len(run) < 2:
        return None
    return run.index(mine) + 1


def day_label(number: int | None) -> str | None:
    return f"Day {number}" if number is not None else None
