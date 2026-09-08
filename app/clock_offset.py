"""Propose the one number a person still has to confirm.

Everything else about a ride is decided from evidence, by the 2026-09-01
policy: candidates are judged, gaps are measured, the story is planned, and
nothing waits on a human. One question genuinely cannot be settled from the
data alone -- whether the camera's clock agreed with the GPS receiver's --
because a camera that is thirteen hours out and a ride that happened
thirteen hours later look identical once you throw the answer away.

So this does not decide it. It reads the two clocks, works out which shifts
would make the footage land inside the ride at all, and puts the best one in
front of a person with the evidence for it: how many recordings fall inside
the ride under that shift, how much of the ride they cover, and how far the
first and last sit from the ride's own ends. The person confirms one number.

Cameras get their clocks wrong in whole hours far more often than in
minutes -- a time zone never set, or set once and never changed for daylight
saving -- so whole-hour and half-hour shifts are what gets tried. A ride
whose footage fits under no shift is reported as exactly that, rather than
having some least-bad number pressed on it.

Local and read-only. It probes video files' metadata and parses the GPX; it
decodes no pictures and opens no network client.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.gps import parse_gpx
from app.video import LocalVideoMetadata, VideoProbeError, probe_local_video_metadata

CLOCK_OFFSET_SCHEMA_VERSION = "clock-offset-proposal-v1"

_VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
# A camera's clock is usually wrong by a whole time zone, sometimes by one of
# the half-hour zones. Minute-level drift is not what this is looking for.
_CANDIDATE_STEPS_S = tuple(
    int(step * 1800) for step in range(-28, 29)
)  # -14 h to +14 h in half hours


class ClockOffsetError(RuntimeError):
    """Raised when no clock offset can be proposed from what is here."""


@dataclass(frozen=True)
class ClockOffsetCandidate:
    """One shift, and how well the footage lands inside the ride under it."""

    offset_s: int
    recordings_inside: int
    recordings_clipped: int
    recordings_total: int
    covered_ride_s: float
    ride_duration_s: float
    lead_in_s: float
    lead_out_s: float

    @property
    def inside_ratio(self) -> float:
        if self.recordings_total <= 0:
            return 0.0
        return self.recordings_inside / self.recordings_total

    @property
    def covered_ratio(self) -> float:
        if self.ride_duration_s <= 0:
            return 0.0
        return self.covered_ride_s / self.ride_duration_s

    def to_dict(self) -> dict[str, object]:
        """Durations and counts only: no path, file name, or capture time."""
        return {
            "offset_s": self.offset_s,
            "offset_hours": round(self.offset_s / 3600.0, 2),
            "recordings_inside": self.recordings_inside,
            "recordings_clipped": self.recordings_clipped,
            "recordings_total": self.recordings_total,
            "inside_ratio": round(self.inside_ratio, 4),
            "covered_ride_s": round(self.covered_ride_s, 1),
            "ride_duration_s": round(self.ride_duration_s, 1),
            "covered_ratio": round(self.covered_ratio, 4),
            "lead_in_s": round(self.lead_in_s, 1),
            "lead_out_s": round(self.lead_out_s, 1),
        }


@dataclass(frozen=True)
class ClockOffsetProposal:
    """What to confirm, and what else was close enough to be worth seeing."""

    best: ClockOffsetCandidate
    runners_up: tuple[ClockOffsetCandidate, ...]

    @property
    def is_unambiguous(self) -> bool:
        """True when nothing else places the footage inside the ride as well.

        An ambiguous proposal is not a failure to report -- it is the case
        where a person's judgement is actually needed, which is the whole
        reason this step exists.
        """
        return all(
            candidate.recordings_inside < self.best.recordings_inside
            for candidate in self.runners_up
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CLOCK_OFFSET_SCHEMA_VERSION,
            "local_only": True,
            "external_data_sent": False,
            "is_unambiguous": self.is_unambiguous,
            "proposed": self.best.to_dict(),
            "runners_up": [candidate.to_dict() for candidate in self.runners_up],
        }


def propose_clock_offset(
    gpx_path: Path,
    video_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    probe: Callable[[Path], LocalVideoMetadata] | None = None,
    candidate_offsets_s: tuple[int, ...] = _CANDIDATE_STEPS_S,
    keep_runners_up: int = 3,
) -> ClockOffsetProposal:
    """Read both clocks and put the most likely shift in front of a person."""
    route = parse_gpx(gpx_path)
    ride_start = route.summary.start_time
    ride_end = route.summary.end_time
    ride_duration_s = (ride_end - ride_start).total_seconds()
    if ride_duration_s <= 0:
        raise ClockOffsetError("the ride's own track covers no time")

    recordings = _recordings(video_root, runner=runner, probe=probe)
    if not recordings:
        raise ClockOffsetError("no readable recording was found to compare clocks with")

    scored = sorted(
        (
            _score(offset_s, recordings, ride_start, ride_end, ride_duration_s)
            for offset_s in candidate_offsets_s
        ),
        key=lambda candidate: (
            # Footage that lies wholly within the ride is the real signal: a
            # recording running past the ride's start or end means the shift
            # has put the camera somewhere the rider was not.
            -candidate.recordings_inside,
            candidate.recordings_clipped,
            -candidate.covered_ride_s,
            abs(candidate.offset_s),
        ),
    )
    best = scored[0]
    if best.recordings_inside == 0:
        raise ClockOffsetError(
            "no whole- or half-hour shift places any recording wholly inside this ride"
        )
    return ClockOffsetProposal(best=best, runners_up=tuple(scored[1 : 1 + keep_runners_up]))


def _recordings(
    video_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    probe: Callable[[Path], LocalVideoMetadata] | None,
) -> tuple[tuple[datetime, float], ...]:
    """Every readable recording as (start on the camera's clock, duration)."""
    if video_root.is_symlink() or not video_root.is_dir():
        raise ClockOffsetError("the video directory is unavailable")
    found: list[tuple[datetime, float]] = []
    for path in sorted(video_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in _VIDEO_SUFFIXES:
            continue
        try:
            metadata = (
                probe(path)
                if probe is not None
                else probe_local_video_metadata(path, runner=runner)
            )
        except (VideoProbeError, ValueError):
            # One unreadable file must not stop a proposal the rest supports.
            continue
        if metadata.recorded_start_time is None or metadata.duration_s <= 0:
            continue
        found.append((metadata.recorded_start_time, metadata.duration_s))
    return tuple(found)


def _score(
    offset_s: int,
    recordings: tuple[tuple[datetime, float], ...],
    ride_start: datetime,
    ride_end: datetime,
    ride_duration_s: float,
) -> ClockOffsetCandidate:
    """How much of this ride the footage would cover under one shift."""
    shift = timedelta(seconds=offset_s)
    windows: list[tuple[datetime, datetime]] = []
    wholly_inside = 0
    clipped = 0
    for start, duration_s in recordings:
        moved_start = start + shift
        moved_end = moved_start + timedelta(seconds=duration_s)
        if moved_end <= ride_start or moved_start >= ride_end:
            continue
        if moved_start >= ride_start and moved_end <= ride_end:
            wholly_inside += 1
        else:
            clipped += 1
        windows.append((max(moved_start, ride_start), min(moved_end, ride_end)))

    covered_s = 0.0
    lead_in_s = 0.0
    lead_out_s = 0.0
    if windows:
        merged: list[list[datetime]] = []
        for start, end in sorted(windows):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
                continue
            merged.append([start, end])
        covered_s = sum((end - start).total_seconds() for start, end in merged)
        lead_in_s = (merged[0][0] - ride_start).total_seconds()
        lead_out_s = (ride_end - merged[-1][1]).total_seconds()

    return ClockOffsetCandidate(
        offset_s=offset_s,
        recordings_inside=wholly_inside,
        recordings_clipped=clipped,
        recordings_total=len(recordings),
        covered_ride_s=covered_s,
        ride_duration_s=ride_duration_s,
        lead_in_s=lead_in_s,
        lead_out_s=lead_out_s,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Propose the camera-to-GPS clock offset for one ride, with the "
            "evidence for it. Reads metadata only; confirms nothing itself."
        )
    )
    parser.add_argument("gpx", type=Path, help="the ride's GPX track")
    parser.add_argument("video_root", type=Path, help="directory holding the recordings")
    args = parser.parse_args()
    try:
        proposal = propose_clock_offset(args.gpx, args.video_root)
    except ClockOffsetError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
