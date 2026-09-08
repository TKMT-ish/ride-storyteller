"""Draw candidates from the footage, not only from where GPS raised an event.

Measured on one real ride, this is where the films were being starved. The
camera ran for 2.3 of the 4.2 hours -- 55% of the journey -- but only 7 of the
24 GPS events fell inside a recording, so the system considered seven
half-minute windows: three and a half minutes out of two and a quarter hours.
Everything else the camera saw was never a candidate at all.

GPS events answer "where did the ride do something", and recordings answer
"where was the camera running". Those overlap far less than the design
assumed. A GPS event is a fine reason to look, but it is not the only one, and
treating it as the only one throws away most of the footage before anything
has judged it.

So a candidate here is any window of a recording that lies inside the ride.
They are enumerated at a stride, given identifiers derived from their own
window so the same window is always the same candidate, and left for
`app.gemini_selection` to choose between once judged. Enumerating is cheap:
this reads catalogue metadata and the GPS track, and opens no video.

Nothing here judges. Narrowing this list by local metrics is the caller's
choice; the point of enumerating generously is that the judgement gets to see
what the camera actually saw.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.gps.turns import SharpTurn
from app.video import VideoCatalog

FOOTAGE_CANDIDATE_SCHEMA_VERSION = "footage-candidates-v1"

# Long enough to tell what a stretch of road is like, short enough that a
# ride yields many of them. Matches the highlight research window.
DEFAULT_WINDOW_S = 12.0
# Far enough apart that neighbouring windows are not the same corner.
DEFAULT_STRIDE_S = 30.0


class FootageCandidateError(ValueError):
    """Raised when candidates cannot be drawn from what is here."""


@dataclass(frozen=True)
class FootageCandidate:
    """One window of one recording, placed on the ride's own clock."""

    candidate_id: str
    asset_id: str
    start_offset_s: float
    duration_s: float
    start_time: datetime

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.asset_id:
            raise ValueError("a footage candidate needs its identifiers")
        if self.start_offset_s < 0:
            raise ValueError("a footage candidate cannot start before its recording")
        if self.duration_s <= 0:
            raise ValueError("a footage candidate must cover a positive duration")
        if self.start_time.tzinfo is None:
            raise ValueError("a footage candidate needs a timezone-aware start")

    @property
    def end_offset_s(self) -> float:
        return self.start_offset_s + self.duration_s

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(seconds=self.duration_s)


def candidate_id_for(start_time: datetime, duration_s: float) -> str:
    """Name a window by the window itself, so it is always the same candidate.

    Deriving the identifier from the time span rather than from a counter
    means two runs over the same ride agree, and a window found twice by
    different means collapses to one candidate rather than two near-identical
    ones.
    """
    material = f"{start_time.timestamp():.3f}:{duration_s:.3f}"
    return f"footage-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def enumerate_footage_candidates(
    catalog: VideoCatalog,
    ride_start: datetime,
    ride_end: datetime,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    stride_s: float = DEFAULT_STRIDE_S,
) -> tuple[FootageCandidate, ...]:
    """Every window of filmed ride, in ride order.

    A window is kept only if it lies wholly inside both its recording and the
    ride. Footage from before the rider set off or after they arrived is not
    part of this journey, and a window running past the end of a recording is
    not footage at all.
    """
    if window_s <= 0 or stride_s <= 0:
        raise FootageCandidateError("a window and stride must both be positive")
    if ride_end <= ride_start:
        raise FootageCandidateError("the ride must cover a positive duration")
    if ride_start.tzinfo is None or ride_end.tzinfo is None:
        raise FootageCandidateError("the ride's span must be timezone-aware")

    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    candidates: list[FootageCandidate] = []
    for entry in catalog.entries:
        base = entry.recorded_start_time + shift
        offset = 0.0
        while offset + window_s <= entry.duration_s:
            start_time = base + timedelta(seconds=offset)
            if start_time >= ride_start and start_time + timedelta(seconds=window_s) <= ride_end:
                candidates.append(
                    FootageCandidate(
                        candidate_id=candidate_id_for(start_time, window_s),
                        asset_id=entry.asset_id,
                        start_offset_s=offset,
                        duration_s=window_s,
                        start_time=start_time,
                    )
                )
            offset += stride_s

    # Two recordings can overlap after a clock correction; the same window
    # must not become two candidates.
    unique: dict[str, FootageCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.candidate_id, candidate)
    return tuple(sorted(unique.values(), key=lambda item: (item.start_time, item.asset_id)))


# How many turn windows a ride may add on top of the stride's. Each one is a
# judgement bought; the second real day had 47 uncovered corners at the
# default thresholds, and the sharpest two dozen are the ones a film wants.
DEFAULT_MAX_TURN_CANDIDATES = 24


def turn_candidates(
    catalog: VideoCatalog,
    ride_start: datetime,
    ride_end: datetime,
    turns: Sequence[SharpTurn],
    existing: Sequence[FootageCandidate],
    *,
    window_s: float = DEFAULT_WINDOW_S,
    max_extra: int = DEFAULT_MAX_TURN_CANDIDATES,
) -> tuple[FootageCandidate, ...]:
    """A window around every sharp turn the stride left unjudged (Q1).

    The stride sees twelve seconds in every thirty; a corner in the other
    eighteen is never shown to the model and can never be chosen. For each
    turn that lies inside a recording and inside no existing window, one
    window is centred on it, kept inside the recording and the ride. The
    sharpest turns come first when there are more than `max_extra`.
    Identifiers come from the window itself, so a turn window that happens
    to coincide with a stride window is the same candidate, not a second.
    """
    if window_s <= 0:
        raise FootageCandidateError("a window must be positive")
    if max_extra < 0:
        raise FootageCandidateError("the number of turn windows cannot be negative")
    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    covered = tuple((c.start_time, c.end_time) for c in existing)
    half = timedelta(seconds=window_s / 2)
    added: dict[str, FootageCandidate] = {}
    for turn in sorted(turns, key=lambda t: -abs(t.degrees)):
        if len(added) >= max_extra:
            break
        middle = turn.middle
        if any(start <= middle <= end for start, end in covered):
            continue
        for entry in catalog.entries:
            recording_start = entry.recorded_start_time + shift
            recording_end = recording_start + timedelta(seconds=entry.duration_s)
            if not recording_start <= middle <= recording_end:
                continue
            start_time = middle - half
            earliest = max(recording_start, ride_start)
            latest = min(recording_end, ride_end) - timedelta(seconds=window_s)
            if latest < earliest:
                break  # the recording or the ride is shorter than one window here
            start_time = min(max(start_time, earliest), latest)
            candidate = FootageCandidate(
                candidate_id=candidate_id_for(start_time, window_s),
                asset_id=entry.asset_id,
                start_offset_s=(start_time - recording_start).total_seconds(),
                duration_s=window_s,
                start_time=start_time,
            )
            if candidate.candidate_id not in {c.candidate_id for c in existing}:
                added.setdefault(candidate.candidate_id, candidate)
            break
    return tuple(sorted(added.values(), key=lambda item: (item.start_time, item.asset_id)))


def recording_spans(catalog: VideoCatalog) -> tuple[tuple[datetime, datetime], ...]:
    """When the camera was running, on the ride's clock, in order."""
    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    return tuple(
        sorted(
            (
                entry.recorded_start_time + shift,
                entry.recorded_start_time + shift + timedelta(seconds=entry.duration_s),
            )
            for entry in catalog.entries
        )
    )


def windows_at(
    catalog: VideoCatalog,
    ride_start: datetime,
    ride_end: datetime,
    starts: Sequence[datetime],
    existing: Sequence[FootageCandidate],
    *,
    window_s: float = DEFAULT_WINDOW_S,
    tolerance_s: float = 3.0,
) -> tuple[FootageCandidate, ...]:
    """A window beginning at each given time, where none already does.

    The moments the track proves -- setting off, pulling in and out of a
    halt, arriving (app.fixed_shots) -- want a window that starts where
    the moment's picture starts, not one centred on it. A window is made
    only inside a recording and inside the ride, kept whole by sliding it
    earlier when it would run past the recording's end; a window that
    already starts within `tolerance_s` is that shot and is not bought
    twice.
    """
    if window_s <= 0:
        raise FootageCandidateError("a window must be positive")
    if tolerance_s < 0:
        raise FootageCandidateError("a tolerance cannot be negative")
    shift = timedelta(seconds=catalog.video_to_gps_offset_s)
    known = tuple(c.start_time for c in existing)
    added: dict[str, FootageCandidate] = {}
    for wanted in starts:
        if any(abs((known_start - wanted).total_seconds()) <= tolerance_s for known_start in known):
            continue
        for entry in catalog.entries:
            recording_start = entry.recorded_start_time + shift
            recording_end = recording_start + timedelta(seconds=entry.duration_s)
            if not recording_start <= wanted <= recording_end:
                continue
            earliest = max(recording_start, ride_start)
            latest = min(recording_end, ride_end) - timedelta(seconds=window_s)
            if latest < earliest:
                break
            start_time = min(max(wanted, earliest), latest)
            candidate = FootageCandidate(
                candidate_id=candidate_id_for(start_time, window_s),
                asset_id=entry.asset_id,
                start_offset_s=(start_time - recording_start).total_seconds(),
                duration_s=window_s,
                start_time=start_time,
            )
            if candidate.candidate_id not in {c.candidate_id for c in existing}:
                added.setdefault(candidate.candidate_id, candidate)
            break
    return tuple(sorted(added.values(), key=lambda item: (item.start_time, item.asset_id)))


def summarise_footage_candidates(
    candidates: tuple[FootageCandidate, ...], ride_duration_s: float
) -> dict[str, object]:
    """Counts and durations only: no identifier, path, or capture time."""
    if ride_duration_s <= 0:
        raise FootageCandidateError("a ride summary needs a positive duration")
    filmed_s = sum(candidate.duration_s for candidate in candidates)
    return {
        "schema_version": FOOTAGE_CANDIDATE_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "candidate_seconds": round(filmed_s, 1),
        "ride_duration_s": round(ride_duration_s, 1),
        "share_of_ride": round(filmed_s / ride_duration_s, 4),
    }
