"""The camera's own GPS: the true clock of a GoPro recording, read from its metadata.

A GoPro writes a metadata track (`gpmd`, the GPMF format) beside the video,
and when its GPS is on that track carries, once a second, the UTC time
(GPSU), the fix quality (GPSF, GPSP) and position and speed samples
(GPS5). The recording's own clock -- the creation time the container
carries -- is whatever the rider set the camera to, in whatever zone; the
GPS time is not. The difference between the two, measured at every second
that had a fix, is the recording's clock offset, to the second, without
any guess about time zones and without the GPX at all.

`app.clock_offset` finds that offset from where the recordings fall inside
the ride; on a long ride several shifts fit equally and it must stop for a
person. This module answers first, and the containment method remains the
fallback for recordings whose GPS never locked (or cameras without one).

The low-resolution proxy a GoPro writes beside each recording (.LRV)
carries the same metadata track and is a tenth of the size, so it is read
when it exists. Nothing here leaves the machine.
"""

from __future__ import annotations

import json
import statistics
import struct
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# A 2D fix or better, with a dilution of precision under this, is a time
# worth trusting. GPSP is DOP x 100: 500 is a DOP of 5.
GOOD_FIX = 2
GOOD_PRECISION = 500
# Below this many trusted seconds a recording's clock is not measured.
MIN_FIXES = 5
# Recordings whose measured offsets disagree by more than this were shot on
# clocks that differ: a person must look.
AGREEMENT_S = 5.0


class GoProGpsError(RuntimeError):
    """Raised when the metadata track cannot be read or holds no usable fix."""


@dataclass(frozen=True)
class GpsFix:
    """One second of GPS from the camera: when (UTC), where, how fast, how sure."""

    seconds_into_recording: int
    utc: datetime
    fix: int
    precision: int
    latitude: float
    longitude: float
    speed_mps: float

    @property
    def is_trusted(self) -> bool:
        return self.fix >= GOOD_FIX and self.precision <= GOOD_PRECISION


@dataclass(frozen=True)
class RecordingClock:
    """How far a recording's own clock is from GPS time."""

    file_name: str
    offset_s: float
    fixes_used: int
    spread_s: float

    def to_dict(self) -> dict[str, object]:
        return {
            "offset_s": round(self.offset_s, 3),
            "fixes_used": self.fixes_used,
            "spread_s": round(self.spread_s, 3),
        }


@dataclass(frozen=True)
class DayClock:
    """The clock offset of one day's recordings, and how sure it is."""

    offset_s: float
    recordings_measured: int
    recordings_inside: int
    recordings_total: int
    recordings_without_gps: int
    spread_s: float
    is_unambiguous: bool

    @property
    def offset_hours(self) -> float:
        return self.offset_s / 3600.0

    def to_dict(self) -> dict[str, object]:
        return {
            "method": "gopro_gps",
            "is_unambiguous": self.is_unambiguous,
            "proposed": {
                "offset_s": round(self.offset_s, 3),
                "offset_hours": round(self.offset_hours, 4),
                "recordings_inside": self.recordings_inside,
                "recordings_total": self.recordings_total,
                "recordings_measured": self.recordings_measured,
                "recordings_without_gps": self.recordings_without_gps,
                "spread_s": round(self.spread_s, 3),
            },
        }


# --- the metadata track ------------------------------------------------------------------


def gpmd_stream_index(path: Path) -> int | None:
    """Which stream of the file is the GoPro metadata, or None."""
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_tag_string",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GoProGpsError("the recording could not be probed")
    for stream in json.loads(completed.stdout or "{}").get("streams", []):
        if stream.get("codec_tag_string") == "gpmd":
            return int(stream["index"])
    return None


def extract_gpmf(path: Path, *, seconds: float | None = None) -> bytes:
    """The raw metadata track, whole or its first `seconds`."""
    index = gpmd_stream_index(path)
    if index is None:
        raise GoProGpsError("the recording has no GoPro metadata track")
    command = ["ffmpeg", "-v", "error", "-y"]
    if seconds is not None:
        command += ["-t", f"{seconds:.3f}"]
    command += ["-i", str(path), "-map", f"0:{index}", "-c", "copy", "-f", "rawvideo", "pipe:1"]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        raise GoProGpsError("the metadata track could not be read")
    return completed.stdout


def _klv(data: bytes, start: int, end: int):
    """Yield (key, type, size, repeat, payload) for each KLV in data[start:end]."""
    at = start
    while at + 8 <= end:
        key = data[at : at + 4]
        kind = data[at + 4]
        size = data[at + 5]
        repeat = struct.unpack(">H", data[at + 6 : at + 8])[0]
        length = size * repeat
        payload = data[at + 8 : at + 8 + length]
        yield key, kind, size, repeat, payload
        at += 8 + ((length + 3) // 4) * 4


def parse_gps_fixes(data: bytes) -> tuple[GpsFix, ...]:
    """One fix per metadata packet (one per second), from the GPS stream inside it."""
    fixes: list[GpsFix] = []
    packet = 0
    for key, kind, _size, _repeat, payload in _klv(data, 0, len(data)):
        if key != b"DEVC" or kind != 0:
            continue
        for skey, skind, _s, _r, spayload in _klv(
            data, _offset_of(data, payload), _offset_of(data, payload) + len(payload)
        ):
            if skey != b"STRM" or skind != 0:
                continue
            fix = _fix_from_stream(spayload, data, packet)
            if fix is not None:
                fixes.append(fix)
        packet += 1
    return tuple(fixes)


def _offset_of(data: bytes, payload: bytes) -> int:
    # payload is a slice of data; recover its start without copying data again
    return len(data) - len(data[data.find(payload) :]) if payload else 0


def _fix_from_stream(payload: bytes, data: bytes, packet: int) -> GpsFix | None:
    fields: dict[bytes, tuple[int, int, int, bytes]] = {}
    for key, kind, size, repeat, value in _klv(payload, 0, len(payload)):
        fields[key] = (kind, size, repeat, value)
    if b"GPS5" not in fields or b"GPSU" not in fields:
        return None
    utc_raw = fields[b"GPSU"][3][:16].decode("ascii", "replace")
    try:
        utc = datetime.strptime(utc_raw, "%y%m%d%H%M%S.%f").replace(tzinfo=UTC)
    except ValueError:
        return None
    fix = struct.unpack(">L", fields[b"GPSF"][3][:4])[0] if b"GPSF" in fields else 0
    precision = struct.unpack(">H", fields[b"GPSP"][3][:2])[0] if b"GPSP" in fields else 9999
    scale = [1, 1, 1, 1, 1]
    if b"SCAL" in fields:
        _kind, size, repeat, value = fields[b"SCAL"]
        count = min(5, repeat if size == 4 else len(value) // 4)
        scale = list(struct.unpack(f">{count}l", value[: 4 * count])) + [1] * (5 - count)
    lat_raw, lon_raw, _alt, speed_raw, _speed3d = struct.unpack(">5l", fields[b"GPS5"][3][:20])
    return GpsFix(
        seconds_into_recording=packet,
        utc=utc,
        fix=int(fix),
        precision=int(precision),
        latitude=lat_raw / (scale[0] or 1),
        longitude=lon_raw / (scale[1] or 1),
        speed_mps=speed_raw / (scale[3] or 1),
    )


# --- clocks ------------------------------------------------------------------------------------


def recording_clock(
    file_name: str, recorded_start_time: datetime, fixes: Sequence[GpsFix]
) -> RecordingClock | None:
    """The recording's clock offset from its trusted fixes, or None if too few."""
    trusted = [f for f in fixes if f.is_trusted]
    if len(trusted) < MIN_FIXES:
        return None
    offsets = [
        (
            f.utc - (recorded_start_time + timedelta(seconds=f.seconds_into_recording))
        ).total_seconds()
        for f in trusted
    ]
    return RecordingClock(
        file_name=file_name,
        offset_s=statistics.median(offsets),
        fixes_used=len(offsets),
        spread_s=max(offsets) - min(offsets),
    )


Reader = Callable[[Path], bytes]


def sidecar_for(path: Path) -> Path:
    """The GoPro low-resolution proxy beside a recording, if the camera wrote one."""
    stem = path.stem
    if len(stem) >= 4 and stem[:2] in ("GX", "GH"):
        candidate = path.with_name("GL" + stem[2:] + ".LRV")
        if candidate.is_file():
            return candidate
    return path


def day_clock(
    recordings: Sequence[tuple[str, datetime, float]],
    video_root: Path,
    ride_start: datetime,
    ride_end: datetime,
    *,
    read: Reader | None = None,
) -> DayClock:
    """The day's clock offset from every recording's GPS, and whether they agree.

    `recordings` are (file name, recorded start on the camera's clock,
    duration). Each recording's offset is measured from its own GPS; the day's
    offset is the median over the recordings that, so placed, lie inside the
    ride. It is unambiguous when those recordings agree within AGREEMENT_S.
    """
    reader = read or (lambda p: extract_gpmf(sidecar_for(p)))
    clocks: list[tuple[RecordingClock, datetime, float]] = []
    without_gps = 0
    for file_name, start, duration_s in recordings:
        try:
            fixes = parse_gps_fixes(reader(video_root / file_name))
        except GoProGpsError:
            without_gps += 1
            continue
        clock = recording_clock(file_name, start, fixes)
        if clock is None:
            without_gps += 1
            continue
        clocks.append((clock, start, duration_s))
    inside = [
        c
        for c, start, duration_s in clocks
        if start + timedelta(seconds=c.offset_s) < ride_end
        and start + timedelta(seconds=c.offset_s + duration_s) > ride_start
    ]
    if not inside:
        raise GoProGpsError("no recording with a GPS fix lies inside this ride")
    offsets = [c.offset_s for c in inside]
    spread = max(offsets) - min(offsets)
    return DayClock(
        offset_s=statistics.median(offsets),
        recordings_measured=len(clocks),
        recordings_inside=len(inside),
        recordings_total=len(recordings),
        recordings_without_gps=without_gps,
        spread_s=spread,
        is_unambiguous=spread <= AGREEMENT_S,
    )


# --- the command --------------------------------------------------------------------------------


def recordings_in(video_root: Path) -> list[tuple[str, datetime, float]]:
    """Every source recording in the folder with its camera-clock start and duration.

    Read through the same catalogue the pipeline builds, so a GoPro recording
    split into chapters gets each chapter's real start (the camera stamps
    every chapter with the recording's start) and the .LRV proxies are not
    counted as recordings. The offset passed is a placeholder: only the
    camera-clock starts are used here.
    """
    from app.video import build_local_video_catalog

    build = build_local_video_catalog(
        video_root, video_to_gps_offset_s=0.0, clock_offset_confirmed=True
    )
    return [(e.file_name, e.recorded_start_time, e.duration_s) for e in build.catalog.entries]


def main(argv: Sequence[str] | None = None) -> None:
    """Measure a day's clock offset from the recordings' own GPS. Prints JSON; reads only."""
    import argparse

    from app.gps import parse_gpx

    parser = argparse.ArgumentParser(
        description=(
            "The clock offset between a folder of GoPro recordings and a ride's GPX, "
            "measured from the cameras' own GPS time. Local only."
        )
    )
    parser.add_argument("gpx", type=Path)
    parser.add_argument("video_root", type=Path)
    parser.add_argument(
        "--hours-around",
        type=float,
        default=16.0,
        help="only recordings whose camera time lies this many hours around the ride are read",
    )
    parser.add_argument(
        "--seconds-read",
        type=float,
        default=90.0,
        help="how much of each metadata track to read; the fix usually comes in the first minute",
    )
    args = parser.parse_args(argv)
    route = parse_gpx(args.gpx)
    ride_start, ride_end = route.summary.start_time, route.summary.end_time
    around = timedelta(hours=args.hours_around)
    near = [
        r
        for r in recordings_in(args.video_root)
        if ride_start - around <= r[1] <= ride_end + around
    ]
    try:
        clock = day_clock(
            near,
            args.video_root,
            ride_start,
            ride_end,
            read=lambda p: extract_gpmf(sidecar_for(p), seconds=args.seconds_read),
        )
    except GoProGpsError as error:
        print(json.dumps({"method": "gopro_gps", "is_unambiguous": False, "error": str(error)}))
        raise SystemExit(1) from error
    print(json.dumps(clock.to_dict(), indent=2))


if __name__ == "__main__":
    main()
